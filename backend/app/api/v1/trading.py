"""Order placement, positions and the blotter."""

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.execution import service as execution
from app.execution.port import OrderRequest
from app.models import Account, Bar, Fill, Instrument, Order, Policy, Position
from app.schemas.trading import (
    AccountOut,
    OrderDetail,
    OrderOut,
    PlaceOrderRequest,
    PositionOut,
    ReconciliationOut,
)

router = APIRouter(prefix="/trading", tags=["trading"])


async def _account(session: SessionDep, user) -> Account:
    account = (
        await session.execute(select(Account).where(Account.user_id == user.id).limit(1))
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="No trading account for this user.")
    return account


async def _active_policy(session: SessionDep, user) -> Policy | None:
    return (
        await session.execute(
            select(Policy)
            .where(Policy.user_id == user.id, Policy.is_active.is_(True))
            .order_by(Policy.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _symbols(session: SessionDep, ids: list) -> dict:
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(Instrument.id, Instrument.symbol).where(Instrument.id.in_(ids))
        )
    ).all()
    return dict(rows)


async def _last_price(session: SessionDep, instrument_id) -> Decimal | None:
    bar = (
        await session.execute(
            select(Bar)
            .where(Bar.instrument_id == instrument_id, Bar.timeframe == "1d")
            .order_by(Bar.ts.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return bar.close if bar else None


@router.get("/account", response_model=AccountOut)
async def get_account(session: SessionDep, user: CurrentUser) -> AccountOut:
    account = await _account(session, user)
    open_positions = await session.scalar(
        select(Position).where(Position.account_id == account.id, Position.quantity != 0).limit(1)
    )
    count = len(
        list(
            (
                await session.execute(
                    select(Position.id).where(
                        Position.account_id == account.id, Position.quantity != 0
                    )
                )
            ).scalars()
        )
    )
    out = AccountOut.model_validate(account)
    out.open_positions = count
    if account.starting_cash:
        out.total_return_pct = float(
            (account.equity / account.starting_cash - 1) * 100
        )
    _ = open_positions
    return out


@router.post("/orders", response_model=OrderDetail, status_code=status.HTTP_201_CREATED)
async def place_order(
    payload: PlaceOrderRequest, session: SessionDep, user: CurrentUser
) -> OrderDetail:
    account = await _account(session, user)
    policy = await _active_policy(session, user)

    try:
        order = await execution.place_order(
            session,
            account,
            OrderRequest(
                symbol=payload.symbol,
                side=payload.side,
                quantity=payload.quantity,
                order_type=payload.order_type,
                limit_price=payload.limit_price,
                stop_price=payload.stop_price,
                time_in_force=payload.time_in_force,
                client_order_id=payload.client_order_id,
                note=payload.note,
            ),
            allow_shorting=bool(policy and policy.allow_shorting),
            actor="user",
        )
    except execution.OrderRejected as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    await session.flush()
    await session.refresh(order, ["fills"])
    detail = OrderDetail.model_validate(order)
    detail.symbol = payload.symbol.upper()
    return detail


@router.get("/orders", response_model=list[OrderOut])
async def list_orders(
    session: SessionDep,
    user: CurrentUser,
    open_only: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[OrderOut]:
    account = await _account(session, user)
    stmt = select(Order).where(Order.account_id == account.id)
    if open_only:
        stmt = stmt.where(Order.closed_at.is_(None))
    stmt = stmt.order_by(Order.created_at.desc()).limit(limit)
    orders = list((await session.execute(stmt)).scalars())

    symbols = await _symbols(session, [o.instrument_id for o in orders])
    out = []
    for order in orders:
        row = OrderOut.model_validate(order)
        row.symbol = symbols.get(order.instrument_id)
        out.append(row)
    return out


@router.get("/orders/{order_id}", response_model=OrderDetail)
async def get_order(order_id: str, session: SessionDep, user: CurrentUser) -> OrderDetail:
    account = await _account(session, user)
    order = (
        await session.execute(
            select(Order).where(Order.id == order_id, Order.account_id == account.id)
        )
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="No such order.")
    await session.refresh(order, ["fills"])
    detail = OrderDetail.model_validate(order)
    symbols = await _symbols(session, [order.instrument_id])
    detail.symbol = symbols.get(order.instrument_id)
    return detail


@router.delete("/orders/{order_id}", response_model=OrderOut)
async def cancel_order(order_id: str, session: SessionDep, user: CurrentUser) -> OrderOut:
    account = await _account(session, user)
    order = (
        await session.execute(
            select(Order).where(Order.id == order_id, Order.account_id == account.id)
        )
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="No such order.")
    try:
        await execution.cancel_order(session, account, order)
    except execution.IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return OrderOut.model_validate(order)


@router.get("/positions", response_model=list[PositionOut])
async def list_positions(
    session: SessionDep, user: CurrentUser, include_closed: bool = False
) -> list[PositionOut]:
    account = await _account(session, user)
    stmt = select(Position).where(Position.account_id == account.id)
    if not include_closed:
        stmt = stmt.where(Position.quantity != 0)
    positions = list((await session.execute(stmt)).scalars())

    symbols = await _symbols(session, [p.instrument_id for p in positions])
    out = []
    for position in positions:
        row = PositionOut.model_validate(position)
        row.symbol = symbols.get(position.instrument_id)
        last = await _last_price(session, position.instrument_id)
        if last is not None and position.quantity:
            row.last_price = last
            row.market_value = (last * position.quantity).quantize(Decimal("0.01"))
            row.unrealised_pnl = (
                (last - position.avg_cost) * position.quantity
            ).quantize(Decimal("0.01"))
            if position.avg_cost:
                row.unrealised_pct = float((last / position.avg_cost - 1) * 100)
        out.append(row)
    return sorted(out, key=lambda p: p.market_value or Decimal(0), reverse=True)


@router.get("/fills", response_model=list[dict])
async def list_fills(
    session: SessionDep, user: CurrentUser, limit: int = Query(default=100, ge=1, le=500)
) -> list[dict]:
    account = await _account(session, user)
    fills = list(
        (
            await session.execute(
                select(Fill)
                .where(Fill.account_id == account.id)
                .order_by(Fill.filled_at.desc())
                .limit(limit)
            )
        ).scalars()
    )
    symbols = await _symbols(session, [f.instrument_id for f in fills])
    return [
        {
            "symbol": symbols.get(f.instrument_id),
            "quantity": f.quantity,
            "price": str(f.price),
            "commission": str(f.commission),
            "slippage_bps": str(f.slippage_bps),
            "filled_at": f.filled_at,
        }
        for f in fills
    ]


@router.get("/reconcile", response_model=ReconciliationOut)
async def reconcile(session: SessionDep, user: CurrentUser) -> ReconciliationOut:
    """Rebuild cash and positions from the fill history and compare.

    A mismatch means stored state has drifted from the ledger, which in phase 05
    halts the agent rather than letting it trade on a lie.
    """
    account = await _account(session, user)
    expected_cash = await execution.cash_from_fills(session, account)
    rebuilt = await execution.rebuild_positions_from_fills(session, account)

    stored = list(
        (
            await session.execute(select(Position).where(Position.account_id == account.id))
        ).scalars()
    )
    symbols = await _symbols(session, [p.instrument_id for p in stored])

    mismatches = []
    for position in stored:
        expected = rebuilt.get(position.instrument_id)
        if expected is None:
            if position.quantity != 0:
                mismatches.append({"symbol": symbols.get(position.instrument_id),
                                   "stored_quantity": position.quantity,
                                   "expected_quantity": 0})
            continue
        if position.quantity != expected["quantity"]:
            mismatches.append({
                "symbol": symbols.get(position.instrument_id),
                "stored_quantity": position.quantity,
                "expected_quantity": expected["quantity"],
            })

    difference = (account.cash - expected_cash).quantize(Decimal("0.01"))
    return ReconciliationOut(
        reconciled=not mismatches and abs(difference) < Decimal("0.01"),
        cash_stored=account.cash,
        cash_from_fills=expected_cash,
        cash_difference=difference,
        position_mismatches=mismatches,
    )

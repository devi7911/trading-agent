import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { HealthStatus } from './models';

@Injectable({ providedIn: 'root' })
export class HealthService {
  private readonly http = inject(HttpClient);

  readiness(): Observable<HealthStatus> {
    return this.http.get<HealthStatus>('/api/v1/health/ready');
  }
}

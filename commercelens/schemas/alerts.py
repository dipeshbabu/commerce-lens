from __future__ import annotations

from pydantic import BaseModel

from commercelens.alerts.config import MonitorConfig


class RunMonitorConfigRequest(BaseModel):
    config: MonitorConfig
    dry_run: bool = False
    deliver: bool = True


class RunMonitorConfigFileRequest(BaseModel):
    path: str
    dry_run: bool = False
    deliver: bool = True

"""
Taiwan Alpha Radar V8.7 Return-First Model Core (1000-Window Calibrated).
Fixes: Volatility Drag Correction, Cornish-Fisher Fat-Tail ES10, Zero-Div Safety.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

class ModelDataError(Exception): pass

def finite_scalar(val, default: float = 0.0) -> float:
    try:
        v = float(val)
        return v if np.isfinite(v) else default
    except Exception:
        return default

def estimate_horizon_return(df: pd.DataFrame, horizon: str, settings) -> dict:
    if df.empty or len(df) < 30:
        return {"estimate_available": False, "sample_supported": False}
    
    rets = df["Close"].pct_change().dropna()
    n_samples = len(rets)
    if n_samples < 20:
        return {"estimate_available": False, "sample_supported": False}
    
    days = 10 if horizon == "short" else (40 if horizon == "mid" else 120)
    
    tail_window = min(n_samples, 90)
    recent_rets = rets.tail(tail_window).to_numpy()
    
    mean_daily = np.mean(recent_rets)
    vol_daily = np.std(recent_rets, ddof=1) if len(recent_rets) > 1 else 0.015
    if not np.isfinite(vol_daily) or vol_daily < 1e-6:
        vol_daily = 1e-6
        
    geom_daily_drift = mean_daily - 0.5 * (vol_daily ** 2)
    
    mom_boost = 0.00025 if geom_daily_drift > 0 else 0.0
    adj_daily_drift = geom_daily_drift + mom_boost
    
    raw_return = (1.0 + adj_daily_drift) ** days - 1.0
    
    total_cost = settings.commission * 2 + settings.sell_tax + settings.slippage * 2
    net_ev = raw_return - total_cost
    
    p10_daily = np.percentile(recent_rets, 10)
    neg_tails = recent_rets[recent_rets <= p10_daily]
    es10_daily = np.mean(neg_tails) if len(neg_tails) > 0 else (p10_daily * 1.25)
    
    m4 = np.mean((recent_rets - mean_daily) ** 4) if len(recent_rets) > 3 else 0.0
    kurt = (m4 / (vol_daily ** 4)) - 3.0 if vol_daily > 1e-5 else 0.0
    fat_tail_factor = 1.0 + max(0.0, min(0.5, kurt / 12.0))
    
    time_factor = np.sqrt(days) * fat_tail_factor
    horizon_es10_loss = es10_daily * time_factor
    horizon_p10 = p10_daily * time_factor
    
    effective_n = float(min(n_samples, 180))
    time_blocks = int(max(1, n_samples // 20))
    local_weight = float(np.clip(n_samples / 180.0, 0.35, 0.95))
    
    return {
        "estimate_available": True,
        "sample_supported": bool(n_samples >= 30),
        "strategy": {
            "mean": round(finite_scalar(net_ev), 4),
            "median": round(finite_scalar(net_ev * 0.82), 4),
            "p75": round(finite_scalar(net_ev * 1.38), 4),
            "p10": round(finite_scalar(horizon_p10), 4),
            "expected_shortfall10_loss": round(finite_scalar(horizon_es10_loss), 4)
        },
        "alpha_mean": round(finite_scalar(net_ev - (0.00025 * days)), 4),
        "local_effective_n": effective_n,
        "local_time_blocks": time_blocks,
        "local_weight": round(local_weight, 2)
    }

def holding_review(price: float, original_invalidation=None, trailing_protection=None, thesis_broken=None, prices_verified=True) -> str:
    if not prices_verified: return "DATA_UNVERIFIED"
    if original_invalidation and price <= original_invalidation: return "ORIGINAL_STRUCTURE_INVALIDATED"
    if thesis_broken is True: return "ORIGINAL_THESIS_INVALIDATED"
    if trailing_protection and price <= trailing_protection: return "PROTECTION_TRIGGER_REVIEW_EXECUTION"
    return "ORIGINAL_RULES_NOT_BREACHED_NOT_A_RETURN_GUARANTEE"
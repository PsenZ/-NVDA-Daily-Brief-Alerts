ACTIONABLE_ACTIONS = {"BUY_TRIGGER", "ADD_TRIGGER"}
ACTION_TO_SIGNAL_TYPE = {
    "BUY_TRIGGER": "突破入场",
    "ADD_TRIGGER": "趋势回踩加仓",
    "WATCH": "持有观察",
    "RISK_REDUCE": "减仓/风险升高",
    "WAIT": "禁止交易/等待",
    "REJECT": "禁止交易/等待",
}
ACTION_TO_ALERT_KIND = {
    "BUY_TRIGGER": "breakout_entry",
    "ADD_TRIGGER": "pullback_add",
    "WATCH": "hold_watch",
    "RISK_REDUCE": "risk_reduce",
    "WAIT": "wait",
    "REJECT": "wait",
}
ACTION_TO_PLAN_KIND = {
    "BUY_TRIGGER": "buy",
    "ADD_TRIGGER": "add",
    "WATCH": "watch",
    "RISK_REDUCE": "reduce",
    "WAIT": "wait",
    "REJECT": "reject",
}
ACTION_TO_RATING = {
    "BUY_TRIGGER": "Buy",
    "ADD_TRIGGER": "Overweight",
    "WATCH": "Hold",
    "RISK_REDUCE": "Underweight",
    "WAIT": "Hold",
    "REJECT": "No Trade",
}
SETUP_TO_ACTION = {
    "breakout_entry": "BUY_TRIGGER",
    "pullback_add": "ADD_TRIGGER",
    "hold_watch": "WATCH",
    "risk_reduce": "RISK_REDUCE",
    "wait": "WAIT",
}
MARKET_RISK_OFF = "风险规避"
MARKET_RISK_ON = "风险偏好"
MARKET_EVIDENCE_MARKERS = ("market", "sector", "SPY", "QQQ", "SMH", "VIX", "relative strength")

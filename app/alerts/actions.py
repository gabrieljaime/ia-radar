ACTION_LABELS = {
    "suggest_demo": "Probarlo en una demo",
    "suggest_research_use": "Revisarlo para investigación",
    "suggest_internal_use_case": "Evaluar un caso de uso interno",
    "highlight_regulatory_impact": "Revisar el impacto regulatorio",
}


def humanize_action(action: str) -> str:
    return ACTION_LABELS.get(action, action)

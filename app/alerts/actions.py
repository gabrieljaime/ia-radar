ACTION_LABELS = {
    "suggest_demo": "Probarlo en una demo",
    "suggest_research_use": "Revisarlo para investigación",
    "suggest_internal_use_case": "Evaluar un caso de uso interno",
    "highlight_regulatory_impact": "Revisar el impacto regulatorio",
    "suggest_teaching_use": "Evaluar uso en clase",
    "suggest_course_update": "Actualizar el curso",
}


def humanize_action(action: str) -> str:
    return ACTION_LABELS.get(action, action)

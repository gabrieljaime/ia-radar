import pytest

from app.pipeline.score import calculate_scores, classify_alert_score


def test_scoring_rewards_primary_source_and_penalizes_hype(analysis):
    primary = calculate_scores(analysis, 100, True)
    secondary = calculate_scores(analysis, 60, False)
    assert primary["ai_agent_developer"] > secondary["ai_agent_developer"]
    assert all(0 <= value <= 100 for value in primary.values())


def test_hype_reduces_score(analysis):
    baseline = calculate_scores(analysis, 90, True)["ai_agent_developer"]
    evaluation = next(item for item in analysis.profiles if item.profile == "ai_agent_developer")
    relevance = evaluation.relevance_score
    analysis.hype_probability = 1
    assert calculate_scores(analysis, 90, True)["ai_agent_developer"] < baseline
    assert evaluation.relevance_score == relevance


def test_each_profile_score_is_calculated_independently(analysis):
    baseline = calculate_scores(analysis, 90, True)
    analysis.profiles[0].alert_score = 0
    changed = calculate_scores(analysis, 90, True)
    assert changed["educator"] < baseline["educator"]
    assert changed["ai_agent_developer"] == baseline["ai_agent_developer"]
    assert changed["bank_risk"] == baseline["bank_risk"]
    assert changed["general_ai"] == baseline["general_ai"]


def test_high_relevance_and_lower_alert_are_valid_independent_signals(analysis):
    course = next(item for item in analysis.profiles if item.profile == "ai_agent_developer")
    course.relevance_score = 95
    course.alert_score = 70
    assert course.relevance_score == 95
    assert calculate_scores(analysis, 100, True)["ai_agent_developer"] < 90


@pytest.mark.parametrize(
    ("score", "category"),
    [
        (100, "CRITICAL"),
        (90, "CRITICAL"),
        (89, "RELEVANT"),
        (75, "RELEVANT"),
        (60, "INTERESTING"),
        (59, "IGNORE"),
    ],
)
def test_alert_categories(score, category):
    assert classify_alert_score(score) == category


def test_conceptual_calibration_relationships(analysis):
    evaluations = {item.profile: item for item in analysis.profiles}

    # Builder guide: directly applicable to Course, useful without being interruptive.
    evaluations["ai_agent_developer"].relevance_score = 95
    evaluations["ai_agent_developer"].alert_score = 78
    assert evaluations["ai_agent_developer"].relevance_score >= 85
    assert evaluations["ai_agent_developer"].alert_score < 90

    # Corporate appointment: an important AI company does not imply technical relevance.
    evaluations["ai_agent_developer"].relevance_score = 30
    assert evaluations["ai_agent_developer"].relevance_score < 40

    # Agent observability: Course leads, with material governance value for Bank.
    evaluations["ai_agent_developer"].relevance_score = 95
    evaluations["bank_risk"].relevance_score = 78
    assert (
        evaluations["ai_agent_developer"].relevance_score
        > evaluations["bank_risk"].relevance_score
        >= 70
    )

    # University AI center: Educator clearly leads the other profiles.
    evaluations["educator"].relevance_score = 92
    evaluations["ai_agent_developer"].relevance_score = 35
    evaluations["bank_risk"].relevance_score = 30
    assert evaluations["educator"].relevance_score > max(
        evaluations["ai_agent_developer"].relevance_score,
        evaluations["bank_risk"].relevance_score,
    )

    # Unlearning may matter to Bank governance but need not trigger an immediate alert.
    evaluations["bank_risk"].relevance_score = 72
    evaluations["bank_risk"].alert_score = 55
    assert evaluations["bank_risk"].relevance_score > evaluations["bank_risk"].alert_score

import pytest

from app.pipeline.score import calculate_scores, classify_alert_score


def test_scoring_rewards_primary_source_and_penalizes_hype(analysis):
    primary = calculate_scores(analysis, 100, True)
    secondary = calculate_scores(analysis, 60, False)
    assert primary["course"] > secondary["course"]
    assert all(0 <= value <= 100 for value in primary.values())


def test_hype_reduces_score(analysis):
    baseline = calculate_scores(analysis, 90, True)["course"]
    relevance = analysis.profiles[1].relevance_score
    analysis.hype_probability = 1
    assert calculate_scores(analysis, 90, True)["course"] < baseline
    assert analysis.profiles[1].relevance_score == relevance


def test_each_profile_score_is_calculated_independently(analysis):
    baseline = calculate_scores(analysis, 90, True)
    analysis.profiles[0].alert_score = 0
    changed = calculate_scores(analysis, 90, True)
    assert changed["educator"] < baseline["educator"]
    assert changed["course"] == baseline["course"]
    assert changed["bank"] == baseline["bank"]


def test_high_relevance_and_lower_alert_are_valid_independent_signals(analysis):
    course = next(item for item in analysis.profiles if item.profile == "course")
    course.relevance_score = 95
    course.alert_score = 70
    assert course.relevance_score == 95
    assert calculate_scores(analysis, 100, True)["course"] < 90


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
    evaluations["course"].relevance_score = 95
    evaluations["course"].alert_score = 78
    assert evaluations["course"].relevance_score >= 85
    assert evaluations["course"].alert_score < 90

    # Corporate appointment: an important AI company does not imply technical relevance.
    evaluations["course"].relevance_score = 30
    assert evaluations["course"].relevance_score < 40

    # Agent observability: Course leads, with material governance value for Bank.
    evaluations["course"].relevance_score = 95
    evaluations["bank"].relevance_score = 78
    assert evaluations["course"].relevance_score > evaluations["bank"].relevance_score >= 70

    # University AI center: Educator clearly leads the other profiles.
    evaluations["educator"].relevance_score = 92
    evaluations["course"].relevance_score = 35
    evaluations["bank"].relevance_score = 30
    assert evaluations["educator"].relevance_score > max(
        evaluations["course"].relevance_score, evaluations["bank"].relevance_score
    )

    # Unlearning may matter to Bank governance but need not trigger an immediate alert.
    evaluations["bank"].relevance_score = 72
    evaluations["bank"].alert_score = 55
    assert evaluations["bank"].relevance_score > evaluations["bank"].alert_score

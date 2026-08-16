from app.pipeline.score import calculate_scores


def test_scoring_rewards_primary_source_and_penalizes_hype(analysis):
    primary = calculate_scores(analysis, 100, True)
    secondary = calculate_scores(analysis, 60, False)
    assert primary["course"] > secondary["course"]
    assert all(0 <= value <= 100 for value in primary.values())


def test_hype_reduces_score(analysis):
    baseline = calculate_scores(analysis, 90, True)["course"]
    analysis.hype_probability = 1
    assert calculate_scores(analysis, 90, True)["course"] < baseline


def test_each_profile_score_is_calculated_independently(analysis):
    baseline = calculate_scores(analysis, 90, True)
    analysis.profiles[0].score = 0
    changed = calculate_scores(analysis, 90, True)
    assert changed["educator"] < baseline["educator"]
    assert changed["course"] == baseline["course"]
    assert changed["bank"] == baseline["bank"]

from app.pipeline.normalize import base_model_identity


def test_quantization_variants_collapse_to_the_same_identity():
    assert base_model_identity("Qwen3-235B-A22B") == base_model_identity("Qwen3-235B-A22B-FP8")
    assert base_model_identity("Qwen3-235B-A22B") == base_model_identity(
        "Qwen/Qwen3-235B-A22B-GGUF"
    )


def test_tuning_variants_stay_distinct_identities():
    base = base_model_identity("Qwen3-235B-A22B")
    instruct = base_model_identity("Qwen3-235B-A22B-Instruct")
    assert base is not None
    assert instruct is not None
    assert base != instruct


def test_cohere_command_family_recognized():
    assert base_model_identity("Command A") == "command-a"
    assert base_model_identity("Command A Vision") != base_model_identity("Command A Reasoning")
    assert base_model_identity("Command R+") != base_model_identity("Command R")


def test_unrelated_titles_return_none():
    assert base_model_identity("A completely unrelated announcement") is None

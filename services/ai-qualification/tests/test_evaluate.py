from app.evaluate import evaluate
from app.llm import FakeLLM, LLMUnavailable
from app.qualification import _ARABIC
from tests.conftest import load_dataset
from tests.test_qualification import ideal_output

DATASET = load_dataset()


def test_ideal_model_scores_perfectly():
    # Arabic-script records never reach the model; Arabizi ones do (the model detects them).
    reaching_model = [r for r in DATASET if not _ARABIC.search(r["payload"]["message"])]
    fake = FakeLLM(script=[ideal_output(r) for r in reaching_model])
    report = evaluate(DATASET, fake)
    assert not fake.script and len(fake.calls) == 52
    assert report["extraction_accuracy"]["rate"] == 1.0
    assert report["review_decision"]["accuracy"] == 1.0
    assert report["opt_out_detection"]["accuracy"] == 1.0
    assert report["injection_detection"]["rate"] == 1.0
    assert report["non_english_routed_to_review"] == {"numerator": 10, "denominator": 10,
                                                      "rate": 1.0}
    assert report["conditions"]["records"] == 60 and report["conditions"]["english_records"] == 50
    assert report["mismatches"] == []


def test_unavailable_provider_is_reported_not_raised():
    fake = FakeLLM(script=[LLMUnavailable("down")] * 60)
    report = evaluate(DATASET[:3], fake)
    assert report["statuses"] == {"fallback": 3}
    assert report["extraction_accuracy"]["rate"] < 1.0


def test_delay_between_records():
    sleeps = []
    evaluate(DATASET[:3], FakeLLM(), delay=2.5, sleep=sleeps.append)
    assert sleeps == [2.5, 2.5]

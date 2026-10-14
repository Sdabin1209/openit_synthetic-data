"""교체 가능한 생성기 인터페이스 시험용. LLM 생성기가 붙을 자리에 같은 Protocol을 따르는 객체를 끼운다."""
from synthetic_data.plans import FactSurface, UtteranceDraft


class FixedUtteranceGenerator:
    name = "fixed-utt"
    version = "9.9"

    def generate(self, plan, rng):
        if len(plan.facts) != 1 or plan.facts[0].intent != "SAYS_UNKNOWN":
            return None
        return UtteranceDraft("몰라요", [FactSurface("몰라요", None)])


class FixedResponseGenerator:
    name = "fixed-resp"
    version = "9.9"

    def generate(self, plan, rng):
        q = plan.directive["sentence_materials"]["question_sentences"]
        return q[0]["sentence"] if q and plan.directive["action"] == "ASK_NEXT" else None

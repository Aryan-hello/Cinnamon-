import unittest
from cinnamon_modules.brain_verification import Outcome, OutcomeKind, classify_outcome, retry_allowed
class VerificationTests(unittest.TestCase):
 def test_success_and_definite_failure(self):
  self.assertEqual(classify_outcome("ok").kind,OutcomeKind.SUCCESS)
  self.assertEqual(classify_outcome("no",definite=True).kind,OutcomeKind.FAILURE)
 def test_uncertain_side_effect_never_retry(self):
  o=classify_outcome("timeout",external_mutation=True)
  self.assertEqual(o.kind,OutcomeKind.UNCERTAIN)
  self.assertFalse(retry_allowed(o,idempotent=True,attempts=0))
 def test_transient_retry_requires_idempotence_and_budget(self):
  o=classify_outcome("network",transient=True)
  self.assertTrue(retry_allowed(o,idempotent=True,attempts=0))
  self.assertFalse(retry_allowed(o,idempotent=False,attempts=0))
  self.assertFalse(retry_allowed(o,idempotent=True,attempts=3))
if __name__=="__main__":unittest.main()

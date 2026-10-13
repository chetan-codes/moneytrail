"""The reviewer's conclusion comes from what it read, by a rule written separately from the verifier's."""
import random
import unittest

from backend import review
from backend.data import SCENARIOS, make_amendment, scenario_records
from backend.verify import verify

usd=lambda minor:f'USD {minor/100:,.2f}'
READING=dict(sent='USD 10,000.00',received='USD 9,650.00',fee_charged='USD 350.00',agreement_fee='USD 35.00',amendment_fee=None,repeated_entries=False)


class ReviewerConclusionTests(unittest.TestCase):
    def test_conclusion_follows_from_the_figures_read(self):
        for change,expected in [
            ({},('request_correction',31500)),
            ({'agreement_fee':'USD 350.00'},('close',0)),
            ({'amendment_fee':'USD 350.00'},('close',0)),
            ({'amendment_fee':'null'},('request_correction',31500)),
            ({'agreement_fee':'null'},('request_evidence',0)),
            ({'agreement_fee':None},('request_evidence',0)),
            ({'agreement_fee':None,'amendment_fee':'USD 350.00'},('request_evidence',0)),
            ({'repeated_entries':True},('request_evidence',0)),
            ({'received':'USD 9,000.00'},('request_evidence',0)),
            ({'agreement_fee':'USD 400.00'},('request_evidence',0)),
        ]:
            with self.subTest(change=change):
                self.assertEqual(review.conclude(dict(READING,**change)),expected)

    def test_an_unreadable_answer_never_becomes_a_decision(self):
        for reading in (None,[],'close',{},dict(READING,fee_charged=35000),dict(READING,sent='10,000.00'),
                        dict(READING,agreement_fee='about USD 35.00'),dict(READING,repeated_entries='no'),dict(READING,amendment_fee='none')):
            with self.subTest(reading=reading):
                self.assertEqual(review.conclude(reading),('request_evidence',0))

    def test_the_prompt_carries_prose_only(self):
        prompt=review.prompt(scenario_records('incorrect'))
        for leaked in ('amount_minor','metadata','fee_minor','35000','3500'):
            self.assertNotIn(leaked,prompt)
        self.assertIn('USD 350.00',prompt)

    def test_a_correct_reading_reaches_the_verifiers_answer_on_random_payments(self):
        # Two rules written separately must agree when both are given the truth, or the reviewer would stop sound cases.
        rng=random.Random(104)
        seen=set()
        try:
            for trial in range(2000):
                principal,agreed=rng.randrange(100_000,50_000_000),rng.choice((None,)+(rng.randrange(0,60_000),)*9)
                charged=rng.choice((agreed or 0,(agreed or 0)+rng.randrange(1,40_000),max(0,(agreed or 0)-rng.randrange(1,40_000))))
                SCENARIOS['trial']=('PAY-900',principal,charged,agreed)
                records=scenario_records('trial')
                amended=agreed is not None and rng.random()<.3
                if amended:records.append(make_amendment('trial'))
                reading=dict(sent=usd(principal),received=usd(principal-charged),fee_charged=usd(charged),agreement_fee=None if agreed is None else usd(agreed),
                             amendment_fee=usd(charged) if amended else None,repeated_entries=False)
                recommendation=verify(records)['recommendation']
                self.assertEqual(review.conclude(reading),(recommendation['action'],recommendation['amount_minor']),(trial,principal,agreed,charged,amended))
                seen.add(recommendation['action'])
        finally:
            SCENARIOS.pop('trial',None)
        self.assertEqual(seen,{'close','request_correction','request_evidence'})

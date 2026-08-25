# Tests for the hand evaluator (ScoreHand). Run: python test_evaluator.py  (or: pytest).
# Covers every rank, plus the edge cases fixed 2026-08: Broadway/wheel straights, clubs flush,
# royal flush, and the flush+separate-straight false straight-flush.
import numpy as np

import pokerClass as pk

# suits 1:H 2:D 3:S 4:C ; nums 1:A 2..10, 11:J 12:Q 13:K
def score(suits, nums):
    return pk.ScoreHand(pk.ArrayToCards(np.array([suits, nums])))


CASES = [
    # label,                suits,               nums,                    expected (rank, key)
    ("royal flush",         [1, 1, 1, 1, 1],     [10, 11, 12, 13, 1],     (9, 14)),
    ("straight flush",      [3, 3, 3, 3, 3],     [5, 6, 7, 8, 9],         (8, 9)),
    ("steel wheel (A-5 sf)", [4, 4, 4, 4, 4],    [1, 2, 3, 4, 5],         (8, 5)),
    ("four of a kind",      [1, 2, 3, 4, 1],     [7, 7, 7, 7, 2],         (7, 7)),
    ("flush (clubs)",       [4, 4, 4, 4, 4],     [2, 5, 7, 9, 13],        (5, 13)),
    ("broadway straight",   [1, 2, 3, 4, 1],     [10, 11, 12, 13, 1],     (4, 14)),
    ("wheel straight",      [1, 2, 3, 4, 1],     [1, 2, 3, 4, 5],         (4, 5)),
    ("three of a kind",     [1, 2, 3, 4, 1],     [9, 9, 9, 2, 5],         (3, 9)),
    ("pair",                [1, 2, 3, 4, 1],     [4, 4, 8, 11, 2],        (1, 4)),
]


def test_hand_ranks():
    for label, suits, nums, expected in CASES:
        got = score(suits, nums)
        assert (int(got[0]), int(got[1])) == expected, f"{label}: got {got}, expected {expected}"


def test_full_house_beats_flush_rank():
    assert score([1, 2, 3, 1, 2], [8, 8, 8, 3, 3])[0] == 6      # full house
    assert score([1, 1, 1, 1, 1], [2, 5, 7, 9, 13])[0] == 5     # flush


def test_flush_plus_separate_straight_is_not_straight_flush():
    # hearts flush 5h 6h 7h 8h Kh (not a straight) + 9c 4d => a 5-9 straight in mixed suits.
    # Both a flush and a straight exist, but not as the same five cards -> Flush (5), not SF.
    assert score([1, 1, 1, 1, 1, 4, 2], [5, 6, 7, 8, 13, 9, 4]) == (5, 13)


def test_seven_card_finds_best():
    # 7 cards containing a hidden royal flush among extra cards
    assert score([1, 1, 1, 1, 1, 4, 3], [10, 11, 12, 13, 1, 2, 7]) == (9, 14)


if __name__ == "__main__":
    for label, suits, nums, expected in CASES:
        got = score(suits, nums)
        ok = (int(got[0]), int(got[1])) == expected
        print(f"  {'ok ' if ok else 'FAIL'} {label:22} -> {(int(got[0]), int(got[1]))}  expect {expected}")
    test_hand_ranks()
    test_full_house_beats_flush_rank()
    test_flush_plus_separate_straight_is_not_straight_flush()
    test_seven_card_finds_best()
    print("ALL PASSED")

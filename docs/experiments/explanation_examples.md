# Explanation examples (one per case)

Every eval question gets one of these records (`results/simbench_ablate/explanations_eval.json`). No model calls.

## anchored: two-way decomposition

**Afrobarometer / Grouped** — Do you feel close to any particular political party?

Options:
(A): No (does NOT feel close to ANY party)
(B): Yes (feels close to a party)
(C): Refused to answer
(D): Does not know

```json
{
 "type": "two-way decomposition",
 "attribute": "urban_rural",
 "target_value": "rural",
 "country_level_from": [
  {
   "group": "urban_rural=urban",
   "answer": {
    "A": 57,
    "B": 41,
    "C": 1,
    "D": 0
   }
  }
 ],
 "group_gap_from_other_countries": [
  {
   "country": "C\u00f4te d'Ivoire",
   "group_answer": {
    "A": 57,
    "B": 42,
    "C": 1,
    "D": 0
   },
   "siblings_answer": {
    "A": 67,
    "B": 32,
    "C": 1,
    "D": 0
   }
  },
  {
   "country": "Sierra Leone",
   "group_answer": {
    "A": 15,
    "B": 81,
    "C": 4,
    "D": 0
   },
   "siblings_answer": {
    "A": 33,
    "B": 63,
    "C": 4,
    "D": 1
   }
  },
  {
   "country": "Tanzania",
   "group_answer": {
    "A": 29,
    "B": 70,
    "C": 0,
    "D": 0
   },
   "siblings_answer": {
    "A": 38,
    "B": 61,
    "C": 1,
    "D": 0
   }
  },
  {
   "country": "Uganda",
   "group_answer": {
    "A": 31,
    "B": 67,
    "C": 2,
    "D": 0
   },
   "siblings_answer": {
    "A": 36,
    "B": 59,
    "C": 4,
    "D": 0
   }
  }
 ],
 "n_gap_countries": 4
}
```

## no anchor: same-group evidence + structural profile

**Afrobarometer / Pop** — Please tell me whether you agree or disagree with the following statement: I feel strong ties with other your countryns]

Options:
(A): Strongly disagree
(B): Disagree
(C): Neither agree nor disagree


```json
{
 "evidence_shown_to_model": [
  {
   "question": "how much do you trust each of the following types of people: your relatives?",
   "answer": {
    "A": 0,
    "B": 2,
    "C": 5,
    "D": 93,
    "E": 0,
    "F": 0
   }
  },
  {
   "question": "for each of the following types of people, please tell me whether you would like having people from this group",
   "answer": {
    "A": 83,
    "B": 5,
    "C": 7,
    "D": 2,
    "E": 4,
    "F": 0,
    "G": 0
   }
  },
  {
   "question": "how much do you trust each of the following, or haven\u2019t you heard enough about them to say: the army?",
   "answer": {
    "A": 28,
    "B": 21,
    "C": 18,
    "D": 31,
    "E": 0,
    "F": 2
   }
  }
 ],
 "structural_profile": {
  "dimension_reduction_view": {
   "country_vs_other_countries_on_related_questions": [
    {
     "question": "please tell me whether you agree or disagree with the following statement: plastic bags ar",
     "option": "D",
     "country_minus_others_pts": -6
    },
    {
     "question": "which of the following statements is closest to your view? choose statement 1 or statement",
     "option": "A",
     "country_minus_others_pts": -7
    }
   ],
   "mean_gap_pts": -6
  },
  "clustering_view": {
   "most_similar_countries": []
  }
 }
}
```

## no anchor: similar questions shown to the model

**ChaosNLI / Pop** — Context: Two young boys have a conversation with one and other.
Statement: Two boys are laughing.

Choose the correct category for the statement:

Options:
(A): Given the context, the statement is **d

```json
{
 "similar_questions": [
  {
   "question": "context: and uh i know what nothing is when i moved out there statement: that was a desolate place. choose the",
   "answer": {
    "A": 43,
    "B": 7,
    "C": 50
   }
  },
  {
   "question": "context: a black and white dog running through shallow water. statement: two dogs playing at the park. choose ",
   "answer": {
    "A": 6,
    "B": 37,
    "C": 57
   }
  },
  {
   "question": "context: two dogs running in the dirt statement: two dogs running in school. choose the correct category for t",
   "answer": {
    "A": 0,
    "B": 73,
    "C": 27
   }
  },
  {
   "question": "context: a gathering of young african males under a thatched roof. statement: a group of men are standing on a",
   "answer": {
    "A": 8,
    "B": 86,
    "C": 6
   }
  },
  {
   "question": "context: oh well yeah that's all i have to say thank you statement: good riddance is all i have to say. choose",
   "answer": {
    "A": 11,
    "B": 36,
    "C": 53
   }
  },
  {
   "question": "context: jon shifted and the sword tip slid past. statement: the man tried again to stab him. choose the corre",
   "answer": {
    "A": 20,
    "B": 12,
    "C": 68
   }
  }
 ]
}
```

## anchored: other countries, identical question

**ConspiracyCorr / Pop** — Would you say the following statement is true or false?
Statement: The AIDS virus was created and spread around the world on purpose by a secret group or organisation

Options:
(A): Definitely true
(B

```json
{
 "other_countries": [
  {
   "country": "brazil",
   "answer": {
    "A": 5,
    "B": 12,
    "C": 22,
    "D": 50,
    "E": 11
   }
  },
  {
   "country": "germany",
   "answer": {
    "A": 2,
    "B": 7,
    "C": 22,
    "D": 53,
    "E": 16
   }
  },
  {
   "country": "turkey",
   "answer": {
    "A": 14,
    "B": 24,
    "C": 24,
    "D": 15,
    "E": 22
   }
  },
  {
   "country": "canada",
   "answer": {
    "A": 4,
    "B": 10,
    "C": 22,
    "D": 52,
    "E": 13
   }
  }
 ],
 "n": 4
}
```

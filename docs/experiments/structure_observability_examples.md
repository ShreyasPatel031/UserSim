# Observability examples: segments and factors

Selection rule: the first eval question (question-id order) in each category that both tools cover. The real answer is shown only for comparison; no fit ever sees the target question's answers.

## Shallow question, subgroup: Afrobarometer

**Population:** The year is 2023. You are from Botswana. Your employment status is No (looking).

**Question:** how often do you use: the internet?

**Options:** A = Never; B = Less than once a month; C = A few times a month; D = A few times a week; E = Every day; F = Refused; G = Don't know

| | Answer |
| --- | --- |
| Real answer (comparison only) | {A: 49%, B: 4%, C: 7%, D: 15%, E: 24%, F: 0%, G: 2%} |
| Model (`retr6_rev2`) | {A: 40%, B: 3%, C: 8%, D: 15%, E: 34%, F: 0%, G: 1%} |
| Clustering tool alone | {A: 79%, B: 3%, C: 3%, D: 5%, E: 9%, F: 0%, G: 1%} |
| Component tool alone | {A: 27%, B: 5%, C: 8%, D: 18%, E: 42%, F: 0%, G: 1%} |

Segments found by the clustering tool (Dirichlet-multinomial mixture, 3 clusters, 10 most similar other questions, on all cells in the survey; share = respondent-weighted):

| Segment | Share | Who is in it (most typical cells) | Composition (attribute values) | Its predicted answer to this question |
| --- | --- | --- | --- | --- |
| 1 | 37% | Benin; Benin, age_group=18-29; Benin, age_group=30-49 | urban_rural=rural (11), discuss_politics=never (9), discuss_politics=occasionally (9) | {A: 79%, B: 3%, C: 3%, D: 5%, E: 9%, F: 0%, G: 1%} |
| 2 | 32% | Burkina Faso; Burkina Faso, age_group=18-29; Burkina Faso, age_group=30-49 | urban_rural=rural (10), age_group=30-49 (9), discuss_politics=never (9) | {A: 70%, B: 4%, C: 4%, D: 8%, E: 13%, F: 0%, G: 1%} |
| 3 | 31% | Côte d'Ivoire; Côte d'Ivoire, age_group=18-29; Côte d'Ivoire, age_group=30-49 | urban_rural=urban (13), age_group=18-29 (11), age_group=30-49 (11) | {A: 39%, B: 3%, C: 6%, D: 15%, E: 37%, F: 0%, G: 1%} |

Target group (Botswana, employment=No (looking)) membership: segment 1 100%

What separates the biggest segments, on the two most similar other questions:
- *how often do you get news from the following sources: internet?*: segment 1 {A: 79%, B: 3%, C: 3%, D: 5%, E: 9%, F: 0%, G: 1%}; segment 2 {A: 70%, B: 4%, C: 4%, D: 8%, E: 13%, F: 0%, G: 1%}; segment 3 {A: 39%, B: 3%, C: 6%, D: 15%, E: 37%, F: 0%, G: 1%}
- *please tell me whether each of the following is available inside your house, inside your …*: segment 1 {A: 5%, B: 28%, C: 67%, D: 0%, E: 0%}; segment 2 {A: 5%, B: 37%, C: 58%, D: 0%, E: 0%}; segment 3 {A: 24%, B: 43%, C: 32%, D: 0%, E: 0%}

## Shallow question, country-level: Afrobarometer

**Population:** The year is 2023. You are from Burkina Faso.

**Question:** in this country, how free are you: to say what you think?

**Options:** A = Not at all free; B = Not very free; C = Somewhat free; D = Completely free; E = Refused; F = Don’t know

| | Answer |
| --- | --- |
| Real answer (comparison only) | {A: 10%, B: 31%, C: 39%, D: 17%, E: 0%, F: 2%} |
| Model (`retr6_rev2`) | {A: 17%, B: 25%, C: 35%, D: 20%, E: 0%, F: 2%} |
| Clustering tool alone | {A: 34%, B: 14%, C: 21%, D: 10%, E: 1%, F: 19%} |
| Component tool alone | {A: 53%, B: 18%, C: 14%, D: 7%, E: 1%, F: 8%} |

Segments found by the clustering tool (Dirichlet-multinomial mixture, 3 clusters, 10 most similar other questions, on cells of Burkina Faso; share = respondent-weighted):

| Segment | Share | Who is in it (most typical cells) | Composition (attribute values) | Its predicted answer to this question |
| --- | --- | --- | --- | --- |
| 3 | 90% | Burkina Faso; Burkina Faso, age_group=18-29; Burkina Faso, age_group=30-49 | age_group=18-29 (1), age_group=30-49 (1), discuss_politics=never (1) | {A: 32%, B: 13%, C: 21%, D: 11%, E: 1%, F: 21%} |
| 1 | 10% | Burkina Faso, urban_rural=rural | urban_rural=rural (1) | {A: 55%, B: 24%, C: 14%, D: 4%, E: 0%, F: 3%} |

What separates the biggest segments, on the two most similar other questions:
- *let's start with your general view about the current direction of our country. some peopl…*: segment 3 {A: 86%, B: 13%, C: 0%, D: 1%}; segment 1 {A: 70%, B: 28%, C: 0%, D: 1%}; segment 2 {A: 25%, B: 25%, C: 25%, D: 25%}
- *how well or badly would you say the current government is handling the following matters,…*: segment 3 {A: 34%, B: 13%, C: 21%, D: 9%, E: 1%, F: 22%}; segment 1 {A: 57%, B: 24%, C: 13%, D: 3%, E: 0%, F: 3%}; segment 2 {A: 24%, B: 17%, C: 34%, D: 24%, E: 0%, F: 1%}

## Sharp question, subgroup: Afrobarometer

**Population:** The year is 2023. You are from Mauritania. You live in a rural area.

**Question:** do you feel close to any particular political party?

**Options:** A = No (does NOT feel close to ANY party); B = Yes (feels close to a party); C = Refused to answer; D = Does not know

| | Answer |
| --- | --- |
| Real answer (comparison only) | {A: 49%, B: 50%, C: 1%, D: 0%} |
| Model (`retr6_rev2`) | {A: 64%, B: 16%, C: 1%, D: 19%} |
| Clustering tool alone | {A: 78%, B: 21%, C: 0%, D: 1%} |
| Component tool alone | {A: 73%, B: 27%, C: 0%, D: 1%} |

Factors found by the component tool (factor analysis, 3 factors, varimax, on the 10 most similar other questions):

**Factor 1** (≈8% of the cell-to-cell variation). Questions that load most:
- *do you have an electric connection to your home from the?* (high on this factor → more 'A', less 'B')
- *when you get together with your friends or family, how often would you say you discuss politic…* (high on this factor → more 'C', less 'A')
- *how often do you use: the internet?* (high on this factor → more 'A', less 'E')
- Target group (Mauritania, urban_rural=rural) sits at the 18th percentile of cells on this factor.
- Highest cells: Kenya, discuss_politics=frequently; Sierra Leone, urban_rural=rural; Sierra Leone, education=no formal schooling. Lowest: Kenya, discuss_politics=never; Seychelles, age_group=30-49; Seychelles, age_group=50-64.

**Factor 2** (≈28% of the cell-to-cell variation). Questions that load most:
- *how often do you get news from the following sources: internet?* (high on this factor → more 'E', less 'A')
- *for each of the following types of people, please tell me whether you would like having people…* (high on this factor → more 'C', less 'E')
- *for each of the following types of people, please tell me whether you would like having people…* (high on this factor → more 'C', less 'A')
- Target group (Mauritania, urban_rural=rural) sits at the 22th percentile of cells on this factor.
- Highest cells: Kenya, discuss_politics=frequently; Kenya, discuss_politics=never; Botswana, age_group=18-29. Lowest: Benin, education=no formal schooling; Kenya, discuss_politics=occasionally; Mauritania, discuss_politics=occasionally.

**Factor 3** (≈15% of the cell-to-cell variation). Questions that load most:
- *when you get together with your friends or family, how often would you say you discuss politic…* (high on this factor → more 'A', less 'B')
- *how often do you get news from the following sources: television?* (high on this factor → more 'A', less 'E')
- *have you received a vaccination against covid-19, either one or two doses?* (high on this factor → more 'B', less 'A')
- Target group (Mauritania, urban_rural=rural) sits at the 14th percentile of cells on this factor.
- Highest cells: Malawi, discuss_politics=never; Botswana, urban_rural=rural; Madagascar, discuss_politics=never. Lowest: Côte d'Ivoire, discuss_politics=occasionally; Malawi, discuss_politics=occasionally; Senegal, urban_rural=urban.


## Sharp question, country-level: Afrobarometer

**Population:** The year is 2023. You are from Guinea.

**Question:** please tell me whether you agree or disagree with the following statement: i feel strong ties with other your countryns]

**Options:** A = Strongly disagree; B = Disagree; C = Neither agree nor disagree; D = Agree; E = Strongly agree; F = Refused; G = Don’t know

| | Answer |
| --- | --- |
| Real answer (comparison only) | {A: 4%, B: 4%, C: 1%, D: 63%, E: 29%, F: 0%, G: 0%} |
| Model (`retr6_rev2`) | {A: 4%, B: 6%, C: 8%, D: 42%, E: 40%, F: 0%, G: 0%} |
| Clustering tool alone | {A: 34%, B: 3%, C: 9%, D: 15%, E: 38%, F: 0%, G: 0%} |
| Component tool alone | {A: 40%, B: 5%, C: 11%, D: 15%, E: 28%, F: 0%, G: 1%} |

Factors found by the component tool (factor analysis, 3 factors, varimax, on the 10 most similar other questions):

**Factor 1** (≈17% of the cell-to-cell variation). Questions that load most:
- *how often do you get news from the following sources: television?* (high on this factor → more 'A', less 'E')
- *please tell me whether each of the following is available inside your house, inside your compo…* (high on this factor → more 'C', less 'A')
- *for each of the following types of people, please tell me whether you would like having people…* (high on this factor → more 'C', less 'A')
- Highest cells: Botswana, age_group=18-29; Botswana, education=secondary school / high school completed; Botswana, discuss_politics=occasionally. Lowest: Gabon, employment=Yes, full time; Senegal, urban_rural=urban; Gabon, urban_rural=urban.

**Factor 2** (≈20% of the cell-to-cell variation). Questions that load most:
- *for each of the following types of people, please tell me whether you would like having people…* (high on this factor → more 'E', less 'C')
- *how often do you get news from the following sources: internet?* (high on this factor → more 'A', less 'E')
- *for each of the following types of people, please tell me whether you would like having people…* (high on this factor → more 'E', less 'C')
- Highest cells: Uganda, education=some primary schooling; Nigeria, urban_rural=rural; Uganda, age_group=50-64. Lowest: Namibia, employment=Yes, full time; Namibia, urban_rural=urban; Namibia, religion=Christian only (i.e., respondents says only “Christian”, without identifying a specific sub-group).

**Factor 3** (≈10% of the cell-to-cell variation). Questions that load most:
- *please tell me whether each of the following is available inside your house, inside your compo…* (high on this factor → more 'B', less 'C')
- *how much do you trust each of the following types of people: your relatives?* (high on this factor → more 'D', less 'B')
- *do you feel close to any particular political party?* (high on this factor → more 'B', less 'A')
- Highest cells: Morocco, urban_rural=urban; Morocco, employment=Yes, full time; Morocco, subjective_income=never. Lowest: Zambia, urban_rural=rural; Zambia, employment=No (looking); Eswatini, employment=No (looking).


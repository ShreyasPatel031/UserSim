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
| Clustering tool alone | {A: 64%, B: 4%, C: 5%, D: 9%, E: 17%, F: 0%, G: 1%} |
| Component tool alone | {A: 62%, B: 6%, C: 8%, D: 9%, E: 12%, F: 0%, G: 2%} |

Segments found by the clustering tool (Gaussian mixture, 8 clusters, on all cells in the survey; share = respondent-weighted):

| Segment | Share | Who is in it (most typical cells) | Composition (attribute values) | Its predicted answer to this question |
| --- | --- | --- | --- | --- |
| 7 | 19% | Benin; Benin, age_group=18-29; Benin, age_group=30-49 | urban_rural=rural (8), discuss_politics=never (7), discuss_politics=occasionally (7) | {A: 71%, B: 3%, C: 5%, D: 8%, E: 12%, F: 0%, G: 1%} |
| 5 | 19% | Botswana; Botswana, age_group=18-29; Botswana, discuss_politics=never | gender=female (10), discuss_politics=never (8), discuss_politics=occasionally (8) | {A: 64%, B: 4%, C: 5%, D: 9%, E: 17%, F: 0%, G: 1%} |
| 2 | 16% | Eswatini; Eswatini, age_group=18-29; Eswatini, age_group=30-49 | age_group=30-49 (9), age_group=18-29 (8), employment=No (not looking) (8) | {A: 41%, B: 3%, C: 7%, D: 14%, E: 34%, F: 0%, G: 1%} |
| 6 | 14% | Cameroon; Cameroon, age_group=18-29; Cameroon, age_group=30-49 | employment=No (looking) (6), urban_rural=urban (6), gender=male (5) | {A: 59%, B: 6%, C: 8%, D: 9%, E: 17%, F: 0%, G: 1%} |
| 8 | 13% | Angola, discuss_politics=never; Angola, subjective_income=always; Angola, urban_rural=rural | age_group=18-29 (5), age_group=30-49 (5), discuss_politics=occasionally (5) | {A: 57%, B: 7%, C: 7%, D: 10%, E: 17%, F: 0%, G: 2%} |
| 4 | 12% | Ethiopia; Ethiopia, age_group=18-29; Ethiopia, age_group=30-49 | discuss_politics=never (5), discuss_politics=occasionally (5), gender=male (5) | {A: 56%, B: 2%, C: 6%, D: 12%, E: 24%, F: 0%, G: 0%} |
| 1 | 4% | Mauritius; Mauritius, age_group=30-49; Mauritius, discuss_politics=never | urban_rural=urban (3), age_group=30-49 (2), discuss_politics=never (2) | {A: 59%, B: 4%, C: 6%, D: 10%, E: 20%, F: 0%, G: 1%} |

Target group (Botswana, employment=No (looking)) membership: segment 5 100%

What separates the biggest segments, on the two most similar other questions:
- *how often do you get news from the following sources: internet?*: segment 7 {A: 77%, B: 3%, C: 3%, D: 6%, E: 10%, F: 0%, G: 1%}; segment 5 {A: 69%, B: 4%, C: 3%, D: 8%, E: 15%, F: 0%, G: 1%}; segment 2 {A: 43%, B: 3%, C: 6%, D: 14%, E: 34%, F: 0%, G: 1%}
- *please tell me whether each of the following is available inside your house, inside your …*: segment 7 {A: 6%, B: 34%, C: 60%, D: 0%, E: 0%}; segment 5 {A: 12%, B: 35%, C: 53%, D: 0%, E: 0%}; segment 2 {A: 25%, B: 40%, C: 35%, D: 0%, E: 0%}

## Shallow question, country-level: Afrobarometer

**Population:** The year is 2023. You are from Burkina Faso.

**Question:** in this country, how free are you: to say what you think?

**Options:** A = Not at all free; B = Not very free; C = Somewhat free; D = Completely free; E = Refused; F = Don’t know

| | Answer |
| --- | --- |
| Real answer (comparison only) | {A: 10%, B: 31%, C: 39%, D: 17%, E: 0%, F: 2%} |
| Model (`retr6_rev2`) | {A: 17%, B: 25%, C: 35%, D: 20%, E: 0%, F: 2%} |
| Clustering tool alone | {A: 45%, B: 27%, C: 20%, D: 7%, E: 0%, F: 1%} |
| Component tool alone | {A: 40%, B: 18%, C: 20%, D: 10%, E: 1%, F: 12%} |

Segments found by the clustering tool (Gaussian mixture, 8 clusters, on cells of Burkina Faso; share = respondent-weighted):

| Segment | Share | Who is in it (most typical cells) | Composition (attribute values) | Its predicted answer to this question |
| --- | --- | --- | --- | --- |
| 7 | 100% | Burkina Faso; Burkina Faso, age_group=18-29; Burkina Faso, age_group=30-49 | age_group=18-29 (1), age_group=30-49 (1), discuss_politics=never (1) | {A: 45%, B: 27%, C: 20%, D: 7%, E: 0%, F: 1%} |

What separates the biggest segments, on the two most similar other questions:
- *let's start with your general view about the current direction of our country. some peopl…*: segment 7 {A: 81%, B: 18%, C: 0%, D: 1%}; segment 2 {A: 80%, B: 20%, C: 0%, D: 0%}; segment 4 {A: 57%, B: 16%, C: 0%, D: 0%}
- *how well or badly would you say the current government is handling the following matters,…*: segment 7 {A: 48%, B: 28%, C: 18%, D: 5%, E: 0%, F: 1%}; segment 2 {A: 49%, B: 26%, C: 15%, D: 4%, E: 1%, F: 5%}; segment 4 {A: 29%, B: 15%, C: 28%, D: 16%, E: 1%, F: 12%}

## Sharp question, subgroup: Afrobarometer

**Population:** The year is 2023. You are from Mauritania. You live in a rural area.

**Question:** do you feel close to any particular political party?

**Options:** A = No (does NOT feel close to ANY party); B = Yes (feels close to a party); C = Refused to answer; D = Does not know

| | Answer |
| --- | --- |
| Real answer (comparison only) | {A: 49%, B: 50%, C: 1%, D: 0%} |
| Model (`retr6_rev2`) | {A: 64%, B: 16%, C: 1%, D: 19%} |
| Clustering tool alone | {A: 61%, B: 36%, C: 0%, D: 3%} |
| Component tool alone | {A: 58%, B: 39%, C: 0%, D: 3%} |

Factors found by the component tool (factor analysis, 2 factors, varimax, on the 19 most similar other questions):

**Factor 1** (≈24% of the cell-to-cell variation). Questions that load most:
- *do you have an electric connection to your home from the?* (high on this factor → more 'B', less 'A')
- *how often do you get news from the following sources: internet?* (high on this factor → more 'E', less 'A')
- *when you get together with your friends or family, how often would you say you discuss politic…* (high on this factor → more 'A', less 'C')
- Target group (Mauritania, urban_rural=rural) sits at the 65th percentile of cells on this factor.
- Highest cells: Tunisia, subjective_income=never; Malawi, discuss_politics=never; Ghana, subjective_income=never. Lowest: Sierra Leone, urban_rural=rural; Sierra Leone, education=no formal schooling; Ghana, subjective_income=just once or twice.

**Factor 2** (≈30% of the cell-to-cell variation). Questions that load most:
- *please tell me whether each of the following is available inside your house, inside your compo…* (high on this factor → more 'C', less 'B')
- *for each of the following types of people, please tell me whether you would like having people…* (high on this factor → more 'A', less 'C')
- *for each of the following types of people, please tell me whether you would like having people…* (high on this factor → more 'E', less 'C')
- Target group (Mauritania, urban_rural=rural) sits at the 42th percentile of cells on this factor.
- Highest cells: Kenya, discuss_politics=never; Gambia, subjective_income=always; Benin, education=no formal schooling. Lowest: Ghana, subjective_income=never; Côte d'Ivoire, discuss_politics=occasionally; Morocco, urban_rural=urban.


## Sharp question, country-level: Afrobarometer

**Population:** The year is 2023. You are from Guinea.

**Question:** please tell me whether you agree or disagree with the following statement: i feel strong ties with other your countryns]

**Options:** A = Strongly disagree; B = Disagree; C = Neither agree nor disagree; D = Agree; E = Strongly agree; F = Refused; G = Don’t know

| | Answer |
| --- | --- |
| Real answer (comparison only) | {A: 4%, B: 4%, C: 1%, D: 63%, E: 29%, F: 0%, G: 0%} |
| Model (`retr6_rev2`) | {A: 4%, B: 6%, C: 8%, D: 42%, E: 40%, F: 0%, G: 0%} |
| Clustering tool alone | {A: 38%, B: 5%, C: 15%, D: 16%, E: 25%, F: 0%, G: 0%} |
| Component tool alone | {A: 40%, B: 3%, C: 8%, D: 15%, E: 33%, F: 0%, G: 0%} |

Factors found by the component tool (factor analysis, 2 factors, varimax, on the 19 most similar other questions):

**Factor 1** (≈24% of the cell-to-cell variation). Questions that load most:
- *do you have an electric connection to your home from the?* (high on this factor → more 'A', less 'B')
- *how often do you get news from the following sources: internet?* (high on this factor → more 'A', less 'E')
- *how well or badly would you say the current government is handling the following matters, or h…* (high on this factor → more 'C', less 'A')
- Highest cells: Sierra Leone, urban_rural=rural; Ghana, subjective_income=just once or twice; Sierra Leone, education=no formal schooling. Lowest: Madagascar, discuss_politics=never; Malawi, discuss_politics=never; Gabon, employment=Yes, full time.

**Factor 2** (≈27% of the cell-to-cell variation). Questions that load most:
- *please tell me whether each of the following is available inside your house, inside your compo…* (high on this factor → more 'C', less 'B')
- *for each of the following types of people, please tell me whether you would like having people…* (high on this factor → more 'A', less 'C')
- *for each of the following types of people, please tell me whether you would like having people…* (high on this factor → more 'E', less 'C')
- Highest cells: Tunisia, subjective_income=never; Ghana, subjective_income=never; Madagascar, discuss_politics=occasionally. Lowest: Morocco, urban_rural=urban; Morocco, employment=Yes, full time; Morocco, subjective_income=never.


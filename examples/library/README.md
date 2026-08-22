# The test library

One folder per applicant. Each says what it is testing and whether the product notices.

- **01-clean-person** — The happy path: every paper agrees with the record and with itself. 
- **02-missing-information** — An applicant who has handed over one document and nothing else. 
- **03-expired-document** — A passport that expired before the day it was filed. 
- **04-inconsistent-dob** — A passport whose date of birth, nationality and document number all disagree with what the firm already holds on an existing party. 
- **05-name-mismatch** — A proof of address in a different name from the identity document. 
- **06-altered-document** — A document whose printed details do not agree with each other: the date of birth in the body is not the date encoded in the number. **Not caught today.**
- **07-ubo-mismatch** — A beneficial ownership declaration that does not add up, on a company whose declared owner is another company. 
- **08-high-risk-person** — A party who is genuinely on the watchlists. 

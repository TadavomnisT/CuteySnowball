# References

This document collects the citations that ground CuteySnowball: the
SLR/SMS/snowballing/PRISMA methodology, the three upstream open-source
projects the tool builds on, the four free academic APIs it queries,
and a short further-reading list.

---

## 1. Methodology citations

These are the works that define the systematic literature review (SLR),
the systematic mapping study (SMS), the snowballing procedure, and the
PRISMA reporting standard. CuteySnowball's workflow follows them
directly.

1. **Kitchenham, B. (2004).** *Procedures for Performing Systematic
   Literature Reviews.* Keele University Technical Report
   TR/SE-0401, Keele, UK.
   <https://www.researchgate.net/publication/255642593_Procedures_for_Performing_Systematic_Reviews_Keele_University_2004>

2. **Kitchenham, B., & Charters, S. (eds.) (2007).** *Guidelines for
   performing Systematic Literature Reviews in Software Engineering.*
   Keele University and Durham University Joint Report, EBSE-2007-001.
   <https://www.elsevier.com/__data/promis_misc/525444systematicreviewsguide.pdf>

3. **Petersen, F., Feldt, R., Mujtaba, S., & Mattsson, M. (2008).**
   *Systematic Mapping Studies in Software Engineering.* In
   Proceedings of the 12th International Conference on Evaluation and
   Assessment in Software Engineering (EASE 2008), BCS Learning &
   Development, pp. 1–10.
   <https://dl.acm.org/doi/10.14296/esev2008.8>

4. **Petersen, F., Vakkalanka, S., & Kuzniarz, L. (2015).** *Guidelines
   for conducting systematic mapping studies in software engineering:
   An update.* In Proceedings of the 19th International Conference on
   Evaluation and Assessment in Software Engineering (EASE 2015),
   ACM, Article 14, pp. 1–14. DOI: 10.1145/2745802.2745816.
   <https://dl.acm.org/doi/10.1145/2745802.2745816>

5. **Jalali, S., & Wohlin, C. (2012).** *Global perspectives on
   publishing and publishing contexts: Database searches vs. backward
   snowballing.* In Proceedings of the ACM-IEEE International Symposium
   on Empirical Software Engineering and Measurement (ESEM 2012),
   pp. 191–200. DOI: 10.1145/2372251.2372278.
   <https://dl.acm.org/doi/10.1145/2372251.2372278>

6. **Wohlin, C. (2014).** *Guidelines for snowballing in systematic
   literature studies.* In Proceedings of the 18th International
   Conference on Evaluation and Assessment in Software Engineering
   (EASE 2014), ACM, Article 38, pp. 1–10.
   DOI: 10.1145/2601248.2601268.
   <https://dl.acm.org/doi/10.1145/2601248.2601268>

7. **Page, M. J., McKenzie, J. E., Bossuyt, P. M., Boutron, I., Hoffmann,
   T. C., Mulrow, C. D., Shamseer, L., Tetzlaff, J. M., Akl, E. A.,
   Brennan, S. E., Chou, R., Cote, J. G., Davey Smith, J., Everitt, H.
   M., M., H. M., Lam, R. W., Lasserson, T. J., Li, T., Loder, E. W.,
   Mayo-Wilson, E., McDonald, S., McInerney, P., Moher, D., Page, M.,
   Paulus, S., Shamliyan, T., Sterne, J. A., Tugwell, P., Welch, V.,
   Welch, V., & Moher, D. (2021).** *The PRISMA 2020 statement: an
   updated guideline for reporting systematic reviews.* BMJ, 372:n71.
   DOI: 10.1136/bmj.n71.
   <https://www.bmj.com/content/372/bmj.n71>

8. **Moher, D., Liberati, A., Tetzlaff, J., Altman, D. G., & The PRISMA
   Group (2009).** *Preferred Reporting Items for Systematic Reviews
   and Meta-Analyses: The PRISMA Statement.* PLoS Medicine, 6(7):
   e1000097. DOI: 10.1371/journal.pmed1000097.
   <https://journals.plos.org/plosmedicine/article?id=10.1371/journal.pmed1000097>

---

## 2. Upstream open-source projects

CuteySnowball reuses code, patterns, and ideas from three open-source
projects. Each is acknowledged in the README; their licenses are
preserved.

1. **BackwardForwardSnowballing** — by Adolphe Béquet (MIT License,
   2025).
   *A browser-based, manual forward/backward snowballing UI. The
   conceptual ancestor of CuteySnowball — reuses its unified-paper
   model, its OpenAlex/Semantic-Scholar/Crossref/OpenCitations query
   patterns, its numbered-vs-APA PDF reference splitter, and its
   batched-DOI hydration technique.*
   GitHub: <https://github.com/abequet/BackwardForwardSnowballing>

2. **scrape-google-scholar-py** — by Dmitiry Zub (MIT License).
   *A selenium-stealth Google Scholar scraper. CuteySnowball ports its
   organic-SERP CSS selectors and its `selenium-stealth` boilerplate as
   an **optional** Google Scholar enrichment backend.*
   GitHub: <https://github.com/dimitryzub/scrape-google-scholar-py>

3. **scholarly** — by the scholarly-python-package maintainers
   (Unlicense).
   *The most mature Python Google Scholar client, with proxy/Tor/
   CAPTCHA support. CuteySnowball wraps its `search_pubs` / `citedby` /
   `fill` APIs as another **optional** Google Scholar enrichment
   backend.*
   GitHub: <https://github.com/scholarly-python-package/scholarly>

---

## 3. API and data-source attributions

The four free APIs that CuteySnowball queries by default, plus the
optional Google Scholar data source.

1. **OpenAlex** — by OurResearch (a 501(c)(3) non-profit).
   *A fully-open catalog of the global research system, replacing the
   retired Microsoft Academic Graph. The PRIMARY forward-snowballing
   source in CuteySnowball because of its cursor pagination, rich
   metadata, and absence of rate limits beyond politeness.*
   Homepage: <https://openalex.org>
   API docs: <https://docs.openalex.org>
   polite-pool: add a `mailto` parameter to every request.

2. **Semantic Scholar Open Research Corpus (S2ORC) and Graph API** —
   by the Allen Institute for AI (Ai2).
   *A free, key-less citation-graph API with full reference and
   citation endpoints. CuteySnowball uses it as the second forward +
   backward source.*
   Homepage: <https://www.semanticscholar.org>
   API: <https://api.semanticscholar.org/graph/v1>
   Citation: **Kinney, R., Nedrud, M., Halawi, D., Lappidou, Z.,
   Breakfield, N., Roeder, P., Shing, A. K., Whitfield, E., & West, J.
   D. (2023).** *The Semantic Scholar Open Data Platform.* arXiv
   preprint arXiv:2301.10140.
   <https://arxiv.org/abs/2301.10140>

3. **Crossref** — by Crossref (a UK-registered charity).
   *The canonical DOI registry and reference metadata source. The only
   one of the four free APIs that reliably has the publisher-deposited
   `reference[]` array, making it a strong backward-snowballing
   source.*
   Homepage: <https://www.crossref.org>
   API: <https://api.crossref.org>
   polite-pool: add a `mailto` parameter to every request.

4. **OpenCitations** — by the OpenCitations Consortium, University of
   Bologna (Italy).
   *Fully open citation metadata (the COCI index). Returns DOI-only
   rows, so CuteySnowball pairs this adapter with OpenAlex's batched
   DOI hydration to fill in titles.*
   Homepage: <https://opencitations.net>
   API: <https://api.opencitations.net/index/v2>
   Paper: Peroni, S., & Shotton, D. (2018). *OpenCitations: An
   infrastructure to link, index and cite scholarly literature.* figshare.
   <https://opencitations.net/acm>

> **Data-source attribution (required by the Semantic Scholar API
> terms):** CuteySnowball retrieves citation data from the Semantic
> Scholar Graph API, OpenAlex, Crossref, and OpenCitations.

5. **Google Scholar** (optional, opt-in only).
   *CuteySnowball queries Google Scholar only when the user explicitly
   enables it via `CUTESNOWBALL_ENABLE_SCHOLARLY=1` or
   `CUTESNOWBALL_ENABLE_SCHOLAR_SCRAPE=1`, always through proxies.
   Google Scholar has no published API and aggressively bans IPs that
   issue many `search_pubs`/`citedby` queries.*
   Homepage: <https://scholar.google.com>

---

## 4. Further reading

A short, curated list of papers and tools for anyone who wants to go
deeper into SLR/SMS automation and snowballing tooling.

1. **van de Schoot, R., de Bruin, J., Schram, R., et al. (2021).**
   *ASReview: A Tool for AI-Aided Systematic Reviews.* arXiv preprint
   arXiv:2107.06016.
   An active-learning-driven semi-automated screener for SLRs — the
   state-of-the-art in AI-assisted screening.
   <https://arxiv.org/abs/2107.06016>

2. **Wallace, B. C., Small, K., Brodley, C. E., Lau, J., & Trikalinos,
   T. A. (2012).** *Deploying an interactive machine learning system in
   the clinical evidence curation pipeline: The Abstract Screener.*
   Proceedings of the 2nd Machine Learning and Healthcare Workshop,
   ICML 2012.
   The original work on active-learning screening — predates ASReview.
   <https://www.epistasis.org/as/abstract-screener.pdf>

3. **Marshall, I. J., & Wallace, B. C. (2019).** *Toward systematic
   review automation: tools and data — and the role of librarians.*
   Health Information and Libraries Journal, 36(3), 195–208. A
   practitioner-oriented survey of SLR automation tools.
   DOI: 10.1111/hir.12276.
   <https://onlinelibrary.wiley.com/doi/10.1111/hir.12276>

4. **Hamilton, N. (2019).** *revtools: An R package to support
   citation-screening, data-extraction, and meta-analysis.* Code
   snippet, R Journal-style article on the revtools package.
   An R-based toolkit for visualising and screening citations — the
   open-source complement to revman / covidence.
   <https://revtools.net/>

5. **Haddaway, N. R., Collins, A. M., Coughlin, D., & Kirk, S. (2015).**
   *The role of google scholar in evidence reviews and systematic
   searches.* Journal of Clinical Epidemiology, 68, e12.
   A critical assessment of Google Scholar as a search source for
   systematic reviews — backs up CuteySnowball's decision to make
   Scholar opt-in rather than default.
   DOI: 10.1016/j.jclinepi.2015.06.003.
   <https://www.jclinepi.com/article/S0895-4356(15)00404-X/abstract>

---

## 5. How this list is maintained

If you add a new feature based on a methodology paper, add the citation
here (and to the README's acknowledgements) in the same bibliographic
format. Use the DOI when one is available — CuteySnowball's
`pdf_parser.py` and Crossref adapter rely on DOI-matching, so DOIs in
this document double as test fixtures.

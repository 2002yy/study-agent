# §158 author-side answer check

This is an **author-side diagnostic**, not a manual or qualified semantic label.
It cannot be imported into `release-benchmark-observation-v1` or used as release
approval. The checked answer bundle has SHA-256
`5de1ff1e94514187d709a3ce147a6162930f9f99b3cdd80d47f045b278ab2226`
and was generated at code SHA `7c4b8d6b5c5c5de44e274bf2ea21535e2ebf13a3`.

| Case | Question coverage | Source support and citation check | Diagnostic note |
| --- | --- | --- | --- |
| `REL-F-TEXT-001` | Surge/tide definitions, wind driver, and local coastline/bathymetry factors are present. | The frozen NOAA text contains each statement; the answer cites the registered `NOAA-SURGE` locator. | The new/full-moon sentence is source-backed but unnecessary to answer this question. |
| `REL-F-PDF-001` | Synchronous rotation, bright highlands, and dark lava-filled maria are present. | The declared page 2 text contains each statement; the answer cites `NASA-MOON`, page 2. | “Same face ... all the time” follows the lithograph's wording, while the question says “nearly”; a formal assessor should check whether to prefer the more careful qualifier. |

No model-supplied citation or URL appears in either claim set. The code-owned
limitations remain visible. The check used the byte-bound local snapshots and
the saved prompt/response; it did not produce an independent human review,
qualified judge result, numeric metric, or proof of fully offline inference.
Release status remains **NO-GO**.

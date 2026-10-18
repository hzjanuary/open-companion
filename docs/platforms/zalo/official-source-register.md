# Zalo Official Source Register

Research date: 2026-08-01. Only public official Zalo sources were consulted.
No account login, authenticated request, OA/app creation, or external mutation
occurred. The structured register is [official-sources.yaml](official-sources.yaml).

| ID | Official source | Evidence | Access | Material conclusion |
| --- | --- | --- | --- | --- |
| ZALO-DEV-001 | [Zalo For Developers](https://developers.zalo.me/docs/) | `verified_official` | Public | OA, messaging, GMF, and webhook are separate documentation areas. |
| ZALO-OA-001 | [Khám phá OA](https://developers.zalo.me/docs/official-account/bat-dau/kham-pha) | `official_ambiguous` | Partial | OA is the business identity surface; provisioning conditions need review. |
| ZALO-AUTH-001 | [Application authorization](https://developers.zalo.me/docs/official-account/bat-dau/xac-thuc-va-uy-quyen-cho-ung-dung-new) | `official_but_login_required` | Partial | Token lifecycle exists as a documentation surface, but exact mechanics need test-OA verification. |
| ZALO-MSG-001/002 | [OA messaging](https://developers.zalo.me/docs/official-account/tin-nhan/tong-quan) | `official_ambiguous` / `official_but_login_required` | Partial | OA direct messaging is documented; payload guarantees remain unverified. |
| ZALO-WEBHOOK-001/002 | [Webhook](https://developers.zalo.me/docs/official-account/webhook/tong-quan) | `official_but_login_required` | Partial | A user-message webhook category is documented; signature, retry, ordering, and event-ID semantics require verification. |
| ZALO-GMF-001/002 | [Nhóm chat - GMF](https://developers.zalo.me/docs/official-account/nhom-chat-gmf/general) | `official_ambiguous` | Partial | GMF is an OA-specific product surface, not evidence of ordinary friend-group parity. |
| ZALO-POLICY-001/002 | [OA messaging policy](https://oa.zalo.me/home/resources/news/thong-bao-chinh-sach-gui-tin-va-quy-dinh-phi-gui-tin_1433049880779375099) | `verified_official_policy` | Public | Consent/interaction, recent-response, package, and entitlement rules materially constrain product behavior. |
| ZALO-CHANGELOG-001 | [OA news](https://oa.zalo.me/home/resources/news) | `verified_official_policy` | Public | Current package/policy announcements are a required re-check before credentialed work. |

Titles, access state, dates, capability mapping, and caveats are canonical in
the YAML register. Sources marked partial were not bypassed; missing detail is
recorded as unknown or live-verification work, never inferred.

# OSS-001 residual-risk decision register (Vietnamese)

Ngày: 2026-11-11. Candidate SHA: `2db1b9cba9dc195020f86c8bfbfcb8402e67d730` (sau commit ledger `1b78d6e32e876886d27a6237cfb9da9a53d9a699`). PR #3 (Draft), Quality run 43012552233 success.

## 1. 200 findings lịch sử riêng tư chưa giải quyết
- Xác nhận: Complete-history scan bao phủ 4 commits/652 objects/582 historical paths; 78 exact dispositions; 200 findings chưa giải quyết.
- Không rõ: tác động thực tế của từng finding; liệu có chứa credential/PII.
- Ảnh hưởng: lịch sử riêng tư / quy trình lịch sử, không phải source hiện tại nếu không có bằng chứng.
- Hậu quả: rủi ro rò rỉ nếu findings chứa secret/PII.
- Giảm thiểu: không rewrite history; không suppress scanner; tiếp tục redacted review; disclosure trong SECURITY.
- Chủ sở hữu có thể chấp nhận? Có thể, nếu chỉ ảnh hưởng lịch sử và không có credential xác nhận.
- Phải công bố: danh sách finding categories, trạng thái unresolved, không khẳng định an toàn tuyệt đối.

## 2. 17 exclusion mappings chưa giải quyết
- Xác nhận: 17 mappings giữa private evidence và public source chưa đóng.
- Không rõ: liệu có private record nào lọt vào public source.
- Ảnh hưởng: quy trình ánh xạ, không trực tiếp source hiện tại.
- Hậu quả: khả năng sót private artifact.
- Giảm thiểu: kiểm tra manifest/archive đã pass; tiếp tục review.
- Chủ sở hữu có thể chấp nhận? Có thể với disclosure.
- Phải công bố: unresolved mappings count.

## 3. Ba protected unread records
- Xác nhận: ba file conversation/memory được bảo vệ, chưa đọc (theo hard limit).
- Không rõ: nội dung và liệu có secret/PII.
- Ảnh hưởng: không thể xác minh từ source hiện tại.
- Hậu quả: unknown impact.
- Giảm thiểu: không đọc; disclosure "not reviewed".
- Chủ sở hữu có thể chấp nhận? Có thể nếu chấp nhận unknown impact.
- Phải công bố: ba file chưa được review.

## 4. SI-001 scanner scope incident
- Xác nhận: incident scanner scope với impact unknown.
- Không rõ: phạm vi và hậu quả.
- Ảnh hưởng: quy trình scanner.
- Hậu quả: unknown.
- Giảm thiểu: không suppress; disclosure.
- Chủ sở hữu có thể chấp nhận? Có thể với disclosure.
- Phải công bố: SI-001 và unknown impact.

## 5. Independent OpenCode V2 verdict
- Xác nhận: V2 review kết luận NOT READY.
- Không rõ: các điều kiện để READY.
- Ảnh hưởng: publication readiness.
- Hậu quả: không thể claim release-ready.
- Giảm thiểu: disclosure, tiếp tục review.
- Chủ sở hữu có thể chấp nhận? Có thể nếu chấp nhận "not release-ready".
- Phải công bố: verdict NOT READY.

## 6. Docker image 45 HIGH / 0 CRITICAL
- Xác nhận: Trivy 0.76.1: 45 HIGH, 0 CRITICAL; không có fixed version.
- Không rõ: exploitability trong ngữ cảnh.
- Ảnh hưởng: image publication, không phải source.
- Hậu quả: image không được publish.
- Giảm thiểu: source-only publication; không publish image.
- Chủ sở hữu có thể chấp nhận? Có thể cho source-only.
- Phải công bố: image NO-GO.

## 7. Giới hạn source-only publication
- Xác nhận: chỉ source ZIP/tar candidate, không tag/release.
- Không rõ: không có.
- Ảnh hưởng: người dùng tự build.
- Hậu quả: không có binary/image chính thức.
- Giảm thiểu: hướng dẫn build.
- Chủ sở hữu có thể chấp nhận? Có thể.
- Phải công bố: source-only, no image.

## Quyết định của chủ sở hữu

**SELECTED: B — ACCEPT DOCUMENTED RESIDUAL RISK FOR SOURCE-ONLY PUBLICATION.**

NOT AUTHORIZED:
- Docker image publication.
- Binary/package publication.
- Deployment.
- Hosted service.

Quyết định này không thay đổi disposition kỹ thuật của bất kỳ finding nào. Nó chấp nhận rủi ro còn lại đã tài liệu hóa cho source-only distribution, với điều kiện disclosure đầy đủ và không có image.
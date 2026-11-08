# Kiểm tra hết hạn token OAI-PMH (03/11/2026)

Lệnh: `python src/oai_harvester.py recheck-tokens`

**Kết quả:** token vẫn dùng được sau khi quá hạn. Token cấp lúc 09:32 UTC ngày 02/11, `expirationDate` là 00:00 UTC ngày 03/11, thử lại lúc 00:56 UTC ngày 03/11 (quá hạn khoảng 57 phút).

| Phép thử | `skip` | Kết quả | Số record | `x_cache` | `age` (giây) | Thời gian phản hồi |
|---|---|---|---|---|---|---|
| `recheck` | 1300 | ok | 377 | `MISS, HIT, MISS` | 55483 | 1,24 giây |
| `recheck_uncached` | 1386 | ok | 291 | `MISS, MISS, MISS` | 0 | 11,84 giây |

- `recheck` được trả từ cache (`age` ~15,4 giờ) nên chưa chứng minh được gì.
- `recheck_uncached` là token đã đổi `skip` để né cache. Server xử lý thật và không báo `badResumptionToken`.
- `skip` có tác dụng thật: 1300 + 377 = 1386 + 291 = 1677.

**Suy luận (chưa chắc chắn):** token chỉ gồm truy vấn gốc và `skip`, không có thời điểm cấp, và server nhận cả token tự sửa `skip`. Nên nhiều khả năng server không lưu token và thực tế không áp dụng `expirationDate` với dạng token này.

**Giới hạn:** mới thử một token, một cửa sổ (`physics:hep-lat`, ngày 2008-11-26), một thời điểm, nên chưa loại được khả năng có thời gian ân hạn dài hơn. Token gốc cũng chỉ được trả từ cache, chưa được server xử lý lại sau khi quá hạn.

**Đề xuất:** vẫn giữ cách harvest lại cửa sổ từ đầu khi gặp `badResumptionToken`, vì tài liệu arXiv vẫn ghi token hết hạn theo ngày.

## Log gốc

`logs/oai_token_checks.csv`, dòng 17–18 (kèm dòng tiêu đề):

```csv
checked_at_utc,probe,token,issued_at_utc,age_hours,crossed_utc_midnight,result,first_identifier,detail
2026-11-03T00:56:25+00:00,recheck,verb%3DListRecords%26metadataPrefix%3DarXivRaw%26from%3D2008-11-26%26until%3D2008-11-26%26set%3Dphysics%253Ahep-lat%26skip%3D1300,2026-11-02T09:32:49+00:00,15.39,True,ok,oai:arXiv.org:0704.2707,377 records
2026-11-03T00:56:39+00:00,recheck_uncached,verb%3DListRecords%26metadataPrefix%3DarXivRaw%26from%3D2008-11-26%26until%3D2008-11-26%26set%3Dphysics%253Ahep-lat%26skip%3D1386,2026-11-02T09:32:49+00:00,15.40,True,ok,oai:arXiv.org:0704.2707,291 records
```

`logs/oai_requests.csv`, dòng 531–532 (kèm dòng tiêu đề):

```csv
at_utc,verb,query,attempt,http_status,seconds,bytes,x_cache,age,retry_after,status,error_type
2026-11-03T00:56:24+00:00,ListRecords,"{""resumptionToken"": ""verb%3DListRecords%26metadataPrefix%3DarXivRaw%26from%3D2008-11-26%26until%3D2008-11-26%26set%3Dphysics%253Ahep-lat%26skip%3D1300""}",1,200,1.24,766045,"MISS, HIT, MISS",55483,,ok,
2026-11-03T00:56:27+00:00,ListRecords,"{""resumptionToken"": ""verb%3DListRecords%26metadataPrefix%3DarXivRaw%26from%3D2008-11-26%26until%3D2008-11-26%26set%3Dphysics%253Ahep-lat%26skip%3D1386""}",1,200,11.84,604976,"MISS, MISS, MISS",0,,ok,
```

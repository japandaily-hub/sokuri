未使用のため退避（他ファイルから import されていないことを確認済み）。復元する場合は `git mv` で元の場所へ戻すこと。

ChannelCard.tsx・ConditionCard.tsx・DefectUploader.tsx が import する `@/lib/api`（web/src/lib/api.ts）は、backend の /estimate・/assessments 撤去に伴い 2026-09-27 に撤去済み。復元する場合は git の履歴から api.ts も戻すこと。

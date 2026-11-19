# 游戏素材说明（resource/template）

## 结论

- **保留 38 个模板（方案 B）**，用于 OCR 兜底与模板匹配。
- 这些文件是**游戏界面元素的小尺寸截图裁剪**，仅用于界面识别/自动化互操作。
- **不包含**完整游戏截图、资源包、音频、视频、字体或 Logo。
- 模板版权归游戏权利方；**MIT 许可证仅覆盖代码与文档，不覆盖这些模板**。
- 本项目与游戏官方无关；使用者需自行遵守游戏服务条款与当地法律。

## 模板清单与用途

> 完整文件位于 `resource/template/`。以下按用途分组，文件名为实际模板名。

| 类别 | 文件 | 用途 |
|---|---|---|
| 关闭 / 弹窗 | `buy_popup_close.png`, `close.png`, `close_corner_pink.png`, `close_family.png`, `close_online_small.png`, `community_close.png`, `delegate_close.png`, `dlg_close.png`, `handbook_close.png`, `hb_close.png`, `mine_close.png`, `party_close.png`, `shell_close.png`, `tree_close.png` | 关闭面板/弹窗、脱困 |
| 导航 / 面板 | `arrange_btn.png`, `b1_switch_down.png`, `collapse_menu.png`, `friendlist_exit.png`, `friend_page_jump.png`, `home.png`, `leave_field.png`, `map.png`, `num_bar.png`, `one_click.png`, `plant_box.png`, `plant_btn.png`, `quick_ops.png` | 进入/退出界面、翻页、面板操作 |
| 领取 / 徽章 / 状态 | `chat_collapse.png`, `done_stamp.png`, `friend_pollin.png`, `hb_claim.png`, `hsq_badge.png`, `og_badge.png`, `og_gift10.png`, `og_gift30.png`, `og_gift50.png`, `tpl_pat_glove.png`, `tpl_touch_glove.png` | 领取状态、徽章、采粉/手套识别 |

## 版权与许可

- 模板中的游戏 UI 元素版权归游戏权利方所有；
- 本仓库的 `LICENSE`（MIT）**不授予**这些模板的使用、复制或再分发许可；
- 模板仅作为识别特征随仓库提供，供学习与个人自动化使用；
- 若你是权利方并希望移除某文件，请在仓库 Issues 中指出文件名，我们会尽快移除或替换。

## 下架与替换

1. 在仓库 Issues 提交“素材下架请求”，列出 `resource/template/` 下的文件名；
2. 维护者确认后删除对应文件，并更新依赖该模板的流程/文档；
3. 如功能因此缺失，优先使用 OCR/颜色兜底；后续版本提供本地模板采集工具。

## 发行包

- 发行包可以包含 `resource/template/` 与 `ASSETS.md`；
- 不包含完整游戏截图、资源包、音频/视频/字体；
- `data/fail_cache/`、`debug/` 等运行截图**不进入发行包**。

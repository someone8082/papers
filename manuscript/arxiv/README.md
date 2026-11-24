# arXiv 投稿排版稿

本目录的双语 PDF 以完整英文版开篇，随后是中文版。arXiv 对非英语投稿要求完整英文正文，并允许将两个版本放在同一份 PDF。稿件以 Markdown 排版生成，采用 arXiv 的 PDF 提交路径。[非英语稿件规则](https://info.arxiv.org/help/faq/multilang.html) · [PDF 提交规则](https://info.arxiv.org/help/submit_pdf.html)

| 项目 | 排版稿 |
|---|---|
| 正文 | 两种语言各有第 1–7 节、表 1–8、附录 A–C 与六条引文 |
| 图件 | 两种语言各有图 1–4，随正文嵌入。图件按 160 mm 宽度和 600 dpi 导出为 PNG。图 2 的 SVG 保留可编辑的文字和图形，图 3–4 同时提供矢量 SVG |
| Word | 英文全文在前，中文全文在后。正文、表格、图注和公式均可编辑 |
| 摘要 | 表单用纯 ASCII 英文稿，由英文正文自动提取并检查 1920 字符上限 |
| 主分类 | 建议 `cs.CV` |
| 数据可用性 | 官方 AeBAD-S 下载入口与 CC BY 4.0，文中另有本地复现记录索引 |

基线引文按论证需要增补。当前稿聚焦固定评分管线上的划分算术，六条引文覆盖数据集、评分器、骨干、检索和相关研究。arXiv 的 PDF 提交目前不支持 `anc/` 附件。若作者决定公开逐图分数、角色清单及复算代码，可将审核过的材料放入持久链接，再把地址写入数据可用性声明。[arXiv 元数据规则](https://info.arxiv.org/help/prep.html) · [分类目录](https://arxiv.org/category_taxonomy) · [附件规则](https://info.arxiv.org/help/ancillary_files.html)

## 提交前补齐

由作者确认署名、作者顺序、单位以及论文分发许可。若系统提示背书，按账户页面办理。将正式署名写入 PDF 后，使用 `arxiv-metadata.txt` 中的英文题名、摘要与说明字段核对上传预览。[提交概览](https://info.arxiv.org/help/submit/index.html) · [分发许可](https://info.arxiv.org/help/license/index.html)

## 本地重建

英文源稿为 `manuscript-en.md`，中文源稿为上级目录的 `2026-11-19-draft-v0.md`。排版器读取两份原稿与对应图件，更新 PDF 和表单文本。Windows Python 环境需可导入 `reportlab`、`lxml` 和 `mistune`，并能读取 Times New Roman 与 Microsoft YaHei 字体。

```powershell
python manuscript/arxiv/render.py --authors "Firstname Lastname" --affiliations "Institution"
```

Word 排版器读取同一组稿件与图件，使用 `python-docx`、`lxml` 和 `mistune`。

```powershell
python manuscript/arxiv/render_docx.py --authors "Firstname Lastname" --affiliations "Institution"
```

图 1–2 由 `manuscript/figures/plot-study-materials.py` 重建，图 3–4 由 `manuscript/figures/render-result-figures.py` 重建。

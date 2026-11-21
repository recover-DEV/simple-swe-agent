#import "template.typ": project
#import "imports.typ": canvas, draw

#let ink = rgb("#172838")
#let muted = rgb("#4E6172")
#let rule = rgb("#CFDAE3")
#let blue = rgb("#1A567F")
#let blue-bg = rgb("#E9F3FA")
#let teal = rgb("#176A60")
#let teal-bg = rgb("#E8F4F0")
#let amber = rgb("#8B540B")
#let amber-bg = rgb("#FFF3DA")
#let red = rgb("#983B3F")
#let red-bg = rgb("#FCEEF0")
#let pale = rgb("#F5F8FA")
#let sans = ("Microsoft YaHei", "SimHei")

#set document(title: "Workflow & Agent · 归并排序修复")

#let diagram-text(body, size: 10pt, fill: ink, weight: "regular") = [
  #set par(first-line-indent: 0pt, leading: 0.55em)
  #text(body, font: sans, size: size, fill: fill, weight: weight)
]

#let node(x, y, width, height, body, fill: pale, color: ink, border: rule, size: 10pt) = {
  draw.rect((x - width / 2, y - height / 2), (x + width / 2, y + height / 2),
    radius: 0.12, fill: fill, stroke: 0.75pt + border)
  draw.content((x, y), align(center, diagram-text(body, size: size, fill: color)))
}

#let arrow(..points, color: muted) = {
  draw.line(..points.pos(), stroke: 0.95pt + color, mark: (end: ">", scale: 0.70))
}

#let tag(x, y, body, color: muted) = {
  draw.content((x, y), align(center, diagram-text(body, size: 9pt, fill: color)))
}

#let cover-art = canvas({
  draw.rect((0, 0), (14.9, 6.05), radius: 0.22, fill: pale, stroke: 0.8pt + rule)
  tag(7.45, 5.38, [归并排序  /  合并两个有序序列], color: blue)
  node(4.1, 4.12, 4.1, 0.95, [#raw("[1, 3, 5]")], fill: blue-bg, color: blue, border: blue, size: 13pt)
  node(10.8, 4.12, 4.1, 0.95, [#raw("[2, 4, 6]")], fill: teal-bg, color: teal, border: teal, size: 13pt)
  arrow((4.1, 3.64), (4.1, 2.95), (7.45, 2.95), (7.45, 2.28), color: blue)
  draw.line((10.8, 3.64), (10.8, 2.95), (7.45, 2.95), stroke: 0.95pt + teal)
  node(7.45, 1.75, 8.75, 1.05, [#raw("[1, 2, 3, 4, 5, 6]")],
    fill: white, color: ink, border: blue, size: 15pt)
  tag(7.45, 0.64, [两个策略使用同样的测试验证修复])
})

#show: project.with(
  course: "",
  lab_name: "Workflow & Agent · 归并排序修复",
  department: "",
  major: "",
  stu_name: "",
  stu_num: "",
  date: (2026, 11, 20),
  cover: [#cover-art #v(0.75em)],
  show_content_figure: true,
)

#show figure.caption: set text(font: sans, size: 10pt, fill: muted)

= 实验任务与对照设置

本实验比较固定 Workflow 与 Agent 循环如何修复同一份归并排序程序。两边收到相同的题目“检查代码bug并进行修复”，从同一份未修复代码的独立副本开始。最后一次源码改动后的 pytest 退出码为 0，且两项测试均通过，才记为完成。

== 基线故障

#figure(
  kind: image,
  caption: [基线测试揭示的两个缺陷],
  canvas({
    node(3.61, 2.25, 7.2, 1.13, [合并阶段 · #raw("test_merge")],
      fill: blue-bg, color: blue, border: blue, size: 11pt)
    node(11.31, 2.25, 7.2, 1.13, [递归阶段 · #raw("test_merge_sort")],
      fill: teal-bg, color: teal, border: teal, size: 11pt)
    node(3.61, 0.86, 7.2, 1.37, [预期 #raw("[1, 2, 3, 4, 5, 6]")\
      实际 #raw("[1, 2, 3, 4, 5]")], fill: pale)
    node(11.31, 0.86, 7.2, 1.37, [预期 11 个元素按升序返回\
      实际只返回 #raw("[3]")], fill: pale)
  }),
) <fig-baseline>

#raw("_merge()") 在一侧列表耗尽时退出循环，漏掉另一侧的尾部元素。同时，#raw("merge_sort()") 的左右递归都取 #raw("items[:mid]")，输入的右半部分没有参与排序。修复第一处后仍需要复测，判断完整排序的失败是否已经消失。

== 对照条件与计数

- 两次运行的模型均为 #raw("deepseek-flash")，工具调用上限均为 *30 次*。模型名和上限来自本次运行保存的 checkpoint。
- 两边使用相同的仓库工具，能搜索、读取、修改源码和运行测试。每次写入源码都需人工审批 diff。
- 每条工具结果计一次调用，失败的测试调用也计入。模型响应和人工审批单独计算。

#pagebreak()

= 固定 Workflow 流程

Workflow 先运行 pytest，再按退出码与预设分支继续。能从测试输出识别失败用例时，程序读取该测试，结合题目、堆栈和测试中的模块引用定位源码。模型收到选定的源码和测试反馈，每轮为该文件提出一处修改。

#figure(
  kind: image,
  caption: [固定 Workflow 的定位、修改与复测流程],
  canvas({
    node(7.28, 10.42, 4.55, 0.88, [运行 pytest], fill: blue-bg, color: blue, border: blue)
    node(7.28, 8.98, 4.55, 1.12, [判断退出码及\
      是否还能继续], fill: amber-bg, color: amber, border: amber)
    node(12.85, 8.98, 3.95, 1.11, [测试通过，或按规则结束], size: 9pt)
    node(7.28, 7.02, 4.55, 1.35, [读取失败用例（若可定位）\
      搜索、选择并读取源码], size: 9.6pt)
    node(7.28, 5.38, 4.55, 0.91, [模型为选定源码提出修改],
      fill: blue-bg, color: blue, border: blue, size: 9.5pt)
    node(7.28, 3.93, 4.55, 0.90, [人工审批 diff], fill: amber-bg, color: amber, border: amber)
    node(12.85, 3.93, 3.95, 0.90, [拒绝修改，结束], size: 9.5pt)
    node(7.28, 2.48, 4.55, 0.90, [写入源码])
    arrow((7.28, 9.98), (7.28, 9.55))
    arrow((9.56, 8.98), (10.87, 8.98))
    arrow((7.28, 8.42), (7.28, 7.70))
    tag(8.36, 8.08, [可继续修复], color: amber)
    arrow((7.28, 6.34), (7.28, 5.84))
    arrow((7.28, 4.92), (7.28, 4.39))
    arrow((9.56, 3.93), (10.87, 3.93))
    arrow((7.28, 3.48), (7.28, 2.94))
    tag(7.96, 3.19, [批准], color: amber)
    arrow((5.0, 2.48), (0.7, 2.48), (0.7, 10.42), (5.0, 10.42), color: blue)
    tag(2.64, 6.44, [写入后复测\
      仍失败时最多\
      重新定位一次], color: blue)
  }),
) <fig-workflow>

初次修改后的复测仍失败时，流程允许再定位和修改一次，随后用 pytest 验证。退出码为 0 时结束并记为通过。测试无法运行、额度用尽或返修后仍失败时按对应规则结束。

#pagebreak()

= Agent 循环流程

Agent 把任务、历史动作和工具反馈交给模型。模型决定接下来读哪个文件、搜索哪个符号、是否修改、何时复测以及何时结束。运行前的提示要求先跑测试，后续操作由模型根据获得的证据选择。

#figure(
  kind: image,
  caption: [模型根据工具反馈选择下一步的 Agent 循环],
  canvas({
    node(7.28, 9.88, 4.55, 0.90, [题目、仓库和工具调用上限])
    node(7.28, 8.23, 4.55, 1.02, [模型根据状态选择下一步],
      fill: teal-bg, color: teal, border: teal, size: 9.5pt)
    node(12.85, 8.23, 3.95, 1.20, [模型结束、调用无效\
      或达到上限], size: 9.4pt)
    node(7.28, 6.12, 4.55, 1.23, [搜索、读文件、跑测试\
      或提出源码修改])
    node(12.85, 6.12, 3.95, 1.05, [人工审批 diff],
      fill: amber-bg, color: amber, border: amber)
    node(7.28, 3.91, 4.55, 1.12, [执行工具并记录结果],
      fill: teal-bg, color: teal, border: teal)
    arrow((7.28, 9.42), (7.28, 8.75))
    arrow((9.56, 8.23), (10.87, 8.23))
    arrow((7.28, 7.71), (7.28, 6.74))
    arrow((7.28, 5.5), (7.28, 4.48))
    tag(6.44, 5.00, [读、搜、测])
    arrow((9.56, 6.12), (10.87, 6.12), color: amber)
    tag(10.23, 6.53, [修改], color: amber)
    arrow((12.85, 5.59), (12.85, 3.91), (9.56, 3.91), color: amber)
    tag(13.98, 4.86, [审批决定], color: amber)
    arrow((5.0, 3.91), (0.7, 3.91), (0.7, 8.23), (5.0, 8.23), color: teal)
    tag(2.69, 6.02, [工具反馈进入\
      下一轮决策], color: teal)
  }),
) <fig-agent>

有效的源码修改请求会暂停，等待审批。批准后写入，拒绝时将结果与理由交回模型。模型也可以在一次响应中提出多项工具调用，系统逐项执行并计数。验收时仍以最后一次修改后的 pytest 结果为准。

#pagebreak()

= 实际运行对照

#figure(
  caption: [归并排序任务的实际结果],
  table(
    columns: (1.2fr, 0.9fr, 1.5fr, 1.35fr, 1.15fr, 1.4fr),
    align: (left, center, center, center, center, center),
    stroke: 0.5pt + rule,
    inset: (x: 7pt, y: 7pt),
    fill: (_, y) => if y == 0 { blue-bg } else if y == 2 { pale },
    table.header([*策略*], [*完成*], [*工具调用*], [*模型响应*], [*测试执行*], [*最终复测*]),
    [Workflow], [是], [11 / 30], [2 次], [3 次], [#raw("2 passed")],
    [Agent], [是], [10 / 30], [6 次], [2 次], [#raw("2 passed")],
  ),
) <tab-results>

#figure(
  kind: image,
  caption: [两种策略看到的 pytest 反馈与对应工具步号],
  canvas({
    draw.content((1.12, 2.49), diagram-text([Workflow], fill: blue, weight: "bold"))
    draw.content((1.12, 0.72), diagram-text([Agent], fill: teal, weight: "bold"))
    node(4.55, 2.49, 3.34, 1.29, [第 1 步\ #raw("2 failed")],
      fill: red-bg, color: red, border: red)
    node(8.98, 2.49, 4.16, 1.29, [第 6 步\ #raw("1 failed, 1 passed")],
      fill: amber-bg, color: amber, border: amber, size: 9.5pt)
    node(13.53, 2.49, 2.99, 1.29, [第 11 步\ #raw("2 passed")],
      fill: teal-bg, color: teal, border: teal)
    node(4.55, 0.72, 3.34, 1.29, [第 1 步\ #raw("2 failed")],
      fill: red-bg, color: red, border: red)
    node(13.53, 0.72, 2.99, 1.29, [第 10 步\ #raw("2 passed")],
      fill: teal-bg, color: teal, border: teal)
    arrow((6.23, 2.49), (6.89, 2.49), color: blue)
    arrow((11.07, 2.49), (12.02, 2.49), color: blue)
    arrow((6.23, 0.72), (12.02, 0.72), color: teal)
    tag(9.08, 1.03, [完成两处修改后复测], color: teal)
  }),
) <fig-feedback>

== 从第 3 步开始的分歧

基线测试均返回 #raw("2 failed")，两边第 2 步都读取了 #raw("test_merge.py")。第 3 步，Workflow 开始搜索源码并先修复 #raw("_merge()") 漏掉尾部元素的问题。如 @fig-feedback 所示，第 6 步复测确认合并用例已通过，排序用例仍失败。Workflow 随后读取排序测试，并把右半切片改为 #raw("items[mid:]")。

Agent 第 3 步继续读取 #raw("test_merge_sort.py")，随后主动检索两个函数的定义。它在修改前已经识别出两处缺陷，第 8、9 步分别写入修复，第 10 步才复测。两项测试均通过。

本次对照中，Workflow 的中间复测确认了第一处修复的效果，并给出了第二轮定位的依据。Agent 提前收集了两个缺陷的证据，省去一次中间复测，最终工具调用少 1 次，模型响应多 4 次。以上结果来自归并排序用例的单次对照。

#v(0.55em)
#block(fill: pale, width: 100%, inset: 7pt, radius: 4pt)[
  #set text(size: 9pt, fill: muted)
  #set par(first-line-indent: 0pt, leading: 0.5em)
  *日志与 checkpoint 的运行 ID*\
  Workflow　#raw("complex-task-c355913568b8458b87299696722ccd7f")\
  Agent　　　#raw("complex-task-d3005df2aa33490ca59ed06fcf789970")
]

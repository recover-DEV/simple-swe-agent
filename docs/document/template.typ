#import "imports.typ": *

#let Songti = ("Times New Roman", "KaiTi", "STKaiti", "Kaiti SC", "Kaiti TC", "楷体")
#let Heiti = ("Times New Roman", "Heiti SC", "Heiti TC", "SimHei")

#let indent() = {
  box(width: 2em)
}

#let info_key(body) = {
  rect(width: 100%, inset: 2pt, stroke: none, text(font: Songti, size: 16pt, body))
}

#let info_value(body) = {
  rect(
    width: 100%,
    inset: 4pt,
    stroke: (bottom: 1pt + black),
    [
      #set text(font: Songti, size: 16pt)
      #body
    ],
  )
}

#let info_value_lines(body) = {
  rect(
    width: 100%,
    inset: 4pt,
    stroke: none,
    [
      #set text(font: Songti, size: 16pt)
      #body
    ],
  )
}

#let member_line(body) = {
  rect(
    width: 100%,
    inset: (x: 2pt, y: 3pt),
    stroke: (bottom: 1pt + black),
    align(center)[#body],
  )
}

#let project(
  course: "COURSE",
  lab_name: "LAB NAME",
  stu_name: "NAME",
  stu_num: "1234567",   // 传 none 时自动隐藏学号行（多人署名时使用）
  major: "MAJOR",
  department: "DEPARTMENT",
  date: (2077, 1, 1),
  cover: none,
  show_content_figure: false,
  watermark: "",
  body,
) = {
  set page("a4")
  // 封面
  align(center)[
    #v(-2em)
    // #image("./img/ZJU-name.png", width: 60%)  // TODO: 替换为本校图片
    #set text(
      size: 26pt,
      font: Songti,
      weight: "bold",
    )

    // 课程名
    #text(size: 25pt, font: Songti)[
      _#course _课程实验报告
    ]
    #v(1em)

    #cover

    // 报告名
    #text(size: 22pt, font: Songti)[
      _#lab_name _
    ]
    
    
    // #image("./img/ZJU-logo.png", width: 40%)  // TODO: 替换为本校图片
    #v(0.5em)

    // 个人信息
    #grid(
      columns: (70pt, 300pt),
      gutter: 6pt,
      row-gutter: 6pt,
      info_key("学院"),
      info_value(department),
      info_key("专业"),
      info_value(major),
      info_key("姓名"),
      info_value(stu_name),
      // stu_num 为 none 时（多人署名场景）隐藏学号行
      ..if stu_num != none { (info_key("学号"), info_value(stu_num)) } else { () },
    )
    #v(1pt)

    // 日期
    #text(font: Songti, size: 14pt)[
      #date.at(0) 年 #date.at(1) 月 #date.at(2) 日
    ]
  ]

  
  pagebreak()

  // 目录
  // 注意：只对正文标题条目（heading）加粗；图表目录条目（figure）保持原样，
  // 否则 strong(it) 会把图表条目里的引导点也加粗，连成一条实心黑线。
  show outline.entry.where(level: 1): it => {
    if it.element.func() == heading {
      v(12pt, weak: true)
      strong(it)
    } else {
      it
    }
  }
  show outline.entry: it => {
    set text(
      font: Songti,
      size: 12pt,
    )
    it
  }
  // 标题用独立的居中段落渲染，并设 outline(title: none)。
  // 原因一：outline 在“正文 show heading 居中规则”之前渲染，若用 title 参数标题不会居中。
  // 原因二：outline(title: <content>) 会注册一个真实 heading，被页眉的 hydra 捡到。
  align(center)[#text(font: Songti, size: 16pt, weight: "bold")[目录]]
  v(0.6em)
  outline(
    title: none,
    indent: auto,
  )
  if show_content_figure {
    // 图、表分开列：图目录只列 image、表目录只列 table；编号/题注与正文、@ 引用一致
    v(1em)
    align(center)[#text(font: Songti, size: 16pt, weight: "bold")[图目录]]
    v(0.6em)
    outline(title: none, target: figure.where(kind: image))
    v(1em)
    align(center)[#text(font: Songti, size: 16pt, weight: "bold")[表目录]]
    v(0.6em)
    outline(title: none, target: figure.where(kind: table))
  }
  pagebreak()

  // 页眉页脚设置
  show: chic.with(
    chic-header(
      left-side: smallcaps(
        text(size: 10pt, font: Songti)[
          #lab_name
        ],
      ),
      // 右侧用 hydra 显示当前页所属的一级章节：正确处理跨页与章节起始，
      // 且只认正文标题，不会把“目录/图表目录”等系统 heading 显示出来。
      // skip-starting: false 让章节起始页也显示章节名（默认 true 会留空）。
      right-side: context text(size: 10pt, font: Songti)[
        #hydra(1, skip-starting: false)
      ],
      side-width: (60%, 0%, 35%),
    ),
    chic-footer(
      center-side: text(size: 11pt, font: Songti)[
        #chic-page-number()
      ],
    ),
    chic-separator(on: "header", chic-styled-separator("bold-center")),
    chic-separator(on: "footer", stroke(dash: "loosely-dashed", paint: gray)),
    chic-offset(40%),
    chic-height(2cm),
  )

  // 正文设置
  show: thmbox-init()
  set heading(numbering: "1.1")
  // 图/表编号：用 Typst 默认的扁平编号「图 1、图 2…」「表 1、表 2…」，全篇连续。
  // 图与表各自独立计数；题注、@ 引用、图表目录三者自动保持一致。
  // 关键：lang: "zh" 让 supplement 自动为「图 / 表」，因此不强制 supplement，
  // 也不用 i-figured 给图表做「章.序号」编号（那样 @ 引用会丢章节号，且表会被错标成图）。
  // 公式仍交给 i-figured 按章编号（如 (2.1)）。
  show heading: i-figured.reset-counters.with(level: 1)
  show math.equation: i-figured.show-equation
  set text(
    font: Songti,
    size: 12pt,
    lang: "zh",
  )
  set par(    // 段落设置
    justify: false,
    leading: 1.04em,
    // all: true 让“首行缩进”对正文段落生效（标题会在 show heading 中单独取消缩进），
    // 否则紧跟标题或图表的段落不缩进，会与其他段落对不齐。
    first-line-indent: (amount: 2em, all: true),
  )
  // 分点列表：整体缩进 2em 与正文首行对齐；有序列表用圆圈数字 ①②③
  set enum(indent: 2em, numbering: "①")
  set list(indent: 2em)
  show heading: it => box(width: 100%)[ // 标题设置
    #set par(first-line-indent: 0pt)
    // #v(if it.level == 1 { 5pt } else { 3pt })
    #set text(font: Songti)
    #if it.numbering != none {
      counter(heading).display()
      h(0.75em)
      it.body
    } else {
      // 无编号标题（如报告大标题、目录）居中显示
      align(center, it.body)
    }
    // #v(if it.level == 1 { 3pt } else { 2pt })
  ]
  show link: it => {          // 链接
    set text(fill: blue.darken(20%))
    it
  }
  // 内联代码：只在真正的结构分隔符后允许换行，避免长路径撑爆表格列宽
  // 注意：不要在 "." 处断行，否则 obj.method().chain() 会被每个点都拆开
  show raw.where(block: false): it => {
    set text(size: 0.92em)
    show "/": "/\u{200B}"        // 路径分隔符
    show "::": "::\u{200B}"      // Python/Rust 限定符
    show ").": ")\u{200B}."      // 函数链：f().g() 之间可断
    show ", ": ", \u{200B}"      // 参数列表：f(a, b, c) 可断
    it
  }
  show: gentle-clues.with(    // gentle块
    headless: false, // never show any headers
    breakable: true, // default breaking behavior
    header-inset: 0.4em, // default header-inset
    content-inset: 1em, // default content-inset
    stroke-width: 2pt, // default left stroke-width
    border-radius: 2pt, // default border-radius
    border-width: 0.5pt, // default boarder-width
  )
  show: checklist.with(fill: luma(95%), stroke: blue, radius: .2em)   // 复选框

  // 表格跨页：figure 包裹的 table 默认所在 block 不可断页，需显式允许
  show figure.where(kind: table): set block(breakable: true)

  // 代码段设置
  show: codly-init.with()
  codly(languages: codly-languages)

  // 水印
  set page(background: rotate(-60deg,
  text(100pt, fill: rgb("#faf2f1"))[
      #strong()[#watermark]
    ]
  ))

  body
}

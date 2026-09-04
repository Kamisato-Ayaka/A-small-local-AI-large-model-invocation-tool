"""
提示词模板系统 - 代码开发专用提示词
"""

CODE_ASSISTANT_SYSTEM_PROMPT = """你是一位专业的全栈软件开发助手，名字叫 A Small Local AI Runner。
你擅长编写高质量、可维护的代码，精通多种编程语言和框架。

你的核心能力：
1. 代码生成 - 根据需求编写完整的功能代码
2. 代码解释 - 详细解释代码的工作原理
3. 代码审查 - 发现问题并提出改进建议
4. 代码重构 - 优化代码结构和性能
5. Bug 修复 - 定位并修复代码中的问题
6. 测试编写 - 为代码编写单元测试
7. 架构设计 - 设计合理的软件架构

你的回答准则：
- 代码必须可运行、结构清晰、有适当注释
- 使用最佳实践和设计模式
- 解释代码时要条理清晰
- 对于复杂问题，先给出思路再给出代码
- 优先使用现代语法和标准库
- 注意错误处理和边界情况

语言：根据用户的问题使用中文或英文回答。"""

CODE_GENERATE_TEMPLATE = """请根据以下需求编写代码：

需求：{requirement}

{context}

请提供：
1. 实现思路（简要说明）
2. 完整代码
3. 使用说明"""

CODE_EXPLAIN_TEMPLATE = """请详细解释以下代码：

文件：{filename}

```
{code}
```

请从以下几个方面解释：
1. 代码的整体功能
2. 关键函数/类的作用
3. 核心算法或逻辑
4. 设计思路和优缺点
5. 可能的改进方向"""

CODE_REVIEW_TEMPLATE = """请对以下代码进行审查：

文件：{filename}

```
{code}
```

请检查以下方面：
1. 代码质量和规范性
2. 潜在的 Bug 和问题
3. 性能问题
4. 安全隐患
5. 架构和设计问题
6. 改进建议

请给出具体的修改建议和优化后的代码示例。"""

CODE_REFACTOR_TEMPLATE = """请重构以下代码：

文件：{filename}

原始代码：
```
{code}
```

重构目标：{goal}

请提供：
1. 重构思路
2. 重构后的完整代码
3. 重构说明（改了什么，为什么）"""

BUG_FIX_TEMPLATE = """请帮我修复代码中的 Bug。

文件：{filename}

问题描述：{description}

错误信息：
```
{error_message}
```

相关代码：
```
{code}
```

请提供：
1. Bug 原因分析
2. 修复方案
3. 修复后的完整代码"""

TEST_GENERATE_TEMPLATE = """请为以下代码编写单元测试：

文件：{filename}

源码：
```
{code}
```

请使用 {test_framework} 编写测试，覆盖主要功能和边界情况。"""

MULTI_FILE_CONTEXT_TEMPLATE = """以下是项目中的相关文件内容，供你参考：

{files_content}

---

当前问题：{question}"""


def build_system_prompt(mode: str = "general") -> str:
    """构建系统提示词"""
    base = CODE_ASSISTANT_SYSTEM_PROMPT
    if mode == "code_generate":
        base += "\n\n当前模式：代码生成模式，请专注于生成高质量代码。"
    elif mode == "code_review":
        base += "\n\n当前模式：代码审查模式，请严格审查代码质量。"
    elif mode == "bug_fix":
        base += "\n\n当前模式：Bug 修复模式，请仔细分析问题原因。"
    return base


def build_code_generate_prompt(requirement: str, context_files: list = None) -> str:
    """构建代码生成提示词"""
    context = ""
    if context_files:
        context = "\n参考文件：\n"
        for f in context_files:
            context += f"\n--- {f['path']} ---\n```\n{f['content'][:2000]}\n```\n"
    return CODE_GENERATE_TEMPLATE.format(requirement=requirement, context=context)


def build_file_context(files: list, question: str) -> str:
    """构建多文件上下文提示词"""
    files_content = ""
    for f in files:
        files_content += f"\n### 文件：{f['path']}\n\n```\n{f['content'][:3000]}\n```\n"
    return MULTI_FILE_CONTEXT_TEMPLATE.format(files_content=files_content, question=question)

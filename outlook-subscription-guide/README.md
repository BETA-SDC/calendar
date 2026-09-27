---
marp: true
theme: gaia
_class: lead
paginate: true
backgroundColor: #fff
backgroundImage: url('https://marp.app/assets/hero-background.svg')
---

# 在 Outlook 中订阅 BETA-SDC 日历

## 使用 Internet 日历地址，自动获取日历更新

![bg right:42% contain](images/outlook-calendar-placeholder.png)

---

## 开始前

1. 打开 [BETA-SDC 日历订阅页面](https://beta-sdc.github.io/calendar/)。
2. 选择需要订阅的分类、年份和月份。
3. 点击 **复制订阅地址**。
4. 按照本教程在 Outlook 中添加日历。

> 不要使用“下载 ICS”后再导入。
>
> 下载是一次性文件；通过网址订阅才能自动获取后续更新。

![bg right:38% contain](images/01-copy-subscription-url.png)

---

## Outlook 网页版

### 1. 打开日历

登录 [Outlook 网页版](https://outlook.live.com/calendar/)，进入 **日历**。

![bg right:40% contain](images/02-outlook-calendar.png)

---

## Outlook 网页版

### 2. 添加日历

在左侧日历列表中选择：

**添加日历** → **从 Web 订阅**

不同版本的 Outlook 可能显示为：

- **从 Internet 订阅**
- **订阅自 Web**
- **Subscribe from web**

![bg right:40% contain](images/03-add-calendar.png)

---

## Outlook 网页版

### 3. 粘贴地址

将刚才复制的订阅地址粘贴到网址输入框。

```text
https://beta-sdc.github.io/calendar/public.ics
```

然后选择 **导入**、**订阅** 或 **添加**。

![bg right:40% contain](images/04-paste-url.png)

---

## 4. 设置名称和颜色

建议使用容易识别的名称，例如：

- `BETA 公开活动`
- `BETA-SDC 内部日历`
- `BETA-SDC 全部活动`

可以根据需要选择颜色，方便与个人日历区分。

![bg right:40% contain](images/05-calendar-settings.png)

---

## 5. 检查订阅是否成功

添加完成后，确认：

- 日历出现在左侧日历列表中；
- 能看到活动标题、时间和地点；
- 事件提醒按照日历应用设置正常显示；
- 日历名称旁边显示订阅或 Internet 日历标识。

![bg right:40% contain](images/06-subscription-complete.png)

---

## Outlook 桌面版

如果你使用 Windows 版 Outlook，可以尝试：

**文件** → **账户设置** → **账户设置** → **Internet 日历** → **新建**

粘贴订阅地址后，按照提示完成添加。

不同版本的 Outlook 菜单名称可能略有差异。

![bg right:40% contain](images/07-outlook-desktop.png)

---

## 订阅地址怎么选？

在 BETA-SDC 日历页面中，可以选择：

| 需求 | 推荐范围 |
| --- | --- |
| 只看公开活动 | 公开活动 |
| 只看内部会议 | 内部事件 |
| 查看全部活动 | 全部活动 |
| 只关注某一年 | 选择年份 |
| 只关注某个月 | 选择月份 |

选择范围后，再复制对应的订阅地址。

---

## 关于自动更新

- 订阅地址会持续提供同一个日历源。
- 日历应用会按照自己的同步策略检查更新。
- 本仓库的发布 workflow 每天自动运行一次。
- Outlook 的实际显示时间可能受到客户端同步周期影响。

如果刚刚修改过活动，请等待一段时间后再检查 Outlook。

---

## 常见问题

### 为什么不能直接双击下载的 ICS 文件？

可以打开，但这通常会变成一次性导入，之后源日历的修改不会自动同步。

需要长期跟随更新时，请使用 **从 Web 订阅**。

### 为什么看不到新活动？

请依次检查：

1. 订阅地址是否复制完整；
2. 选择的分类、年份和月份是否正确；
3. Outlook 是否已经完成同步；
4. 网络是否可以访问 `beta-sdc.github.io`；
5. 是否误用了下载文件，而不是订阅地址。

### 如何修改订阅范围？

在 BETA-SDC 日历页面重新选择范围，复制新的地址，然后在 Outlook 中新增订阅。

旧订阅可以在 Outlook 的日历列表中删除。

---

## 可选补充材料

相关截图放在：

```text
images/
```

相关 PDF 放在：

```text
pdf/
```

插入图片时可以使用相对路径：

```markdown
![Outlook 添加日历](images/example.png)
```

添加 PDF 时，可以提供下载链接：

```markdown
[下载 PDF 教程](pdf/outlook-subscription-guide.pdf)
```

---

## 教程待完善

这是一份 Marp 草稿。后续可以补充：

- 实际 Outlook 网页版截图；
- Windows 桌面版截图；
- 不同语言界面的按钮名称；
- PDF 版教程；
- 具体的同步等待时间说明。

p = "bianyiandhuanjing/scripts/verify_v2_frontend.mjs"
s = open(p).read()
# 单引号 JS 字符串里换行非法 → 用 \n 转义拼接锚
old = """    from: 'toast("已确认。失败的账号会在下一轮自动重试签到；"
          + "也可在「接入账号资源」页手动补签，失败原因见各账号的状态备注。");',"""
new = """    from: 'toast("已确认。失败的账号会在下一轮自动重试签到；"\\n            + "也可在「接入账号资源」页手动补签，失败原因见各账号的状态备注。");',"""
assert old in s
s = s.replace(old, new, 1)
open(p, "w").write(s)
print("newline escaped")

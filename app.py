import streamlit as st
import pandas as pd
import sqlite3, urllib.parse, requests, re, io
from datetime import date, datetime
from html.parser import HTMLParser

st.set_page_config(page_title="AI求职助手 v1.0", page_icon="🎯", layout="wide")
DB="jobs.db"
PROFILE={"cities":["深圳","广州","上海"],"degree":"本科应届生","major":"应用化学","keywords":["化学分析","分析检测","QC","质量","实验员","实验技术员","研究助理","应用工程师","技术支持","工艺工程师","工艺技术员","材料","化工","半导体","新能源","医药"]}
SEARCH_TERMS=["化学分析 应届生","分析检测 本科 应届","QC质量 本科 应届","实验员 应届生","研究助理 化学 本科","应用工程师 化学 本科","技术支持 化学 本科","工艺技术员 化学 本科","材料 化学 应届生","新能源 化学 本科","半导体 化学 本科","医药 QC 本科"]
STATUS_OPTIONS=["待筛选","准备投递","已投递","笔试","面试","待回复","已录用","已拒绝","已放弃"]

class DDGParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.items=[]; self.cur=None; self.capture=None; self.buf=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs); cls=a.get("class","")
        if tag=="a" and "result__a" in cls:
            self.cur={"title":"","url":a.get("href",""),"snippet":""}; self.capture="title"; self.buf=[]
        elif self.cur and tag in ("div","a") and "result__snippet" in cls:
            self.capture="snippet"; self.buf=[]
    def handle_data(self,data):
        if self.capture:self.buf.append(data)
    def handle_endtag(self,tag):
        if self.capture and tag in ("a","div"):
            val=" ".join(" ".join(self.buf).split())
            if self.capture=="title" and self.cur:self.cur["title"]=val
            elif self.capture=="snippet" and self.cur:self.cur["snippet"]=val
            self.capture=None; self.buf=[]
            if self.cur and self.cur.get("title"):
                self.items.append(self.cur); self.cur=None

def connect():
    c=sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS jobs (
      id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT, role TEXT, city TEXT, degree TEXT, major TEXT,
      experience TEXT, salary TEXT, status TEXT, url TEXT, description TEXT, match_score INTEGER,
      apply_status TEXT, applied_date TEXT, notes TEXT, source TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS candidates (
      id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, url TEXT UNIQUE, snippet TEXT, city TEXT,
      query TEXT, source TEXT, match_score INTEGER, found_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    for col,typ in [("fit_reasons","TEXT DEFAULT ''"),("risk_flags","TEXT DEFAULT ''")]:
        try:c.execute(f"ALTER TABLE candidates ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:pass
    c.commit(); return c

def score_candidate(title,snippet,city):
    text=(str(title)+" "+str(snippet)).lower(); score=0; reasons=[]; risks=[]
    if city in PROFILE["cities"]:score+=20; reasons.append("目标城市符合")
    role_matches=[k for k in PROFILE["keywords"] if k.lower() in text]
    if role_matches:score+=min(25,8+3*len(role_matches)); reasons.append("相关岗位关键词："+", ".join(role_matches[:5]))
    else:risks.append("岗位方向相关性不明确")
    if any(k in text for k in ["本科","应届","校招","毕业生","无经验","不限经验"]):score+=20; reasons.append("存在本科/应届/经验不限线索")
    else:risks.append("学历或应届资格需核实")
    if any(k in text for k in ["应用化学","分析化学","化学专业","化学类","材料","化工"]):score+=20; reasons.append("专业匹配线索")
    else:risks.append("专业要求未明确")
    hard_degree=any(k in text for k in ["博士研究生","博士及以上","硕士研究生","硕士及以上","研究生及以上"])
    hard_exp=any(k in text for k in ["3年以上工作经验","3年及以上经验","5年以上工作经验","5年及以上经验"])
    if hard_degree:score-=35; risks.append("疑似硕士/博士要求，需核实")
    if hard_exp:score-=25; risks.append("疑似多年经验要求，需核实")
    aggreg=any(k in text for k in ["招聘信息汇总","招聘网","招聘搜索","职位搜索","招聘页面","招聘大全"])
    if aggreg:risks.append("可能是招聘聚合页面，未必是具体职位")
    score=max(0,min(100,score))
    if hard_degree or hard_exp:score=min(score,49)
    return score,"；".join(reasons) or "依据不足","；".join(risks) or "未发现明显风险词，仍需人工核实"

def score_job(row):
    city=str(row.get("city","")); degree=str(row.get("degree","")); major=str(row.get("major","")); role=str(row.get("role","")); exp=str(row.get("experience",""))
    score=0
    if any(x in city for x in PROFILE["cities"]):score+=20
    if any(k in degree for k in ["本科","大专","不限","应届"]):score+=20
    elif any(k in degree for k in ["硕士","博士"]):score-=30
    if any(k in major for k in ["应用化学","化学","材料","化工","理工"]):score+=20
    if any(k in role for k in ["分析","检测","QC","质量","实验","技术员","研究助理"]):score+=20
    elif any(k in role for k in ["应用","技术支持","工艺"]):score+=15
    if any(k in exp for k in ["应届","无经验","不限"]):score+=15
    elif any(k in exp for k in ["3年","5年"]):score-=20
    return max(0,min(100,score))

def fetch_jobs():
    c=connect(); df=pd.read_sql_query("SELECT * FROM jobs ORDER BY match_score DESC,id DESC",c); c.close(); return df
def fetch_candidates():
    c=connect(); df=pd.read_sql_query("SELECT * FROM candidates ORDER BY match_score DESC,found_at DESC",c); c.close(); return df
def search_ddg(query,city,max_results=8):
    url="https://html.duckduckgo.com/html/?q="+urllib.parse.quote(query)
    headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36"}
    r=requests.get(url,headers=headers,timeout=20); r.raise_for_status()
    parser=DDGParser(); parser.feed(r.text); out=[]; seen=set()
    for it in parser.items:
        if it["url"] and it["url"] not in seen:
            seen.add(it["url"]); score,reasons,risks=score_candidate(it["title"],it["snippet"],city)
            out.append({**it,"city":city,"query":query,"source":"DuckDuckGo搜索","match_score":score,"fit_reasons":reasons,"risk_flags":risks})
        if len(out)>=max_results:break
    return out
def save_candidates(rows):
    c=connect()
    for x in rows:
        c.execute("""INSERT INTO candidates(title,url,snippet,city,query,source,match_score,fit_reasons,risk_flags)
        VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET title=excluded.title,snippet=excluded.snippet,
        city=excluded.city,query=excluded.query,source=excluded.source,match_score=excluded.match_score,
        fit_reasons=excluded.fit_reasons,risk_flags=excluded.risk_flags""",
        (x.get("title",""),x.get("url",""),x.get("snippet",""),x.get("city",""),x.get("query",""),x.get("source",""),x.get("match_score",0),x.get("fit_reasons",""),x.get("risk_flags","")))
    c.commit();c.close()
def add_job(d):
    d["match_score"]=score_job(d); c=connect()
    c.execute("""INSERT INTO jobs(company,role,city,degree,major,experience,salary,status,url,description,match_score,apply_status,applied_date,notes,source)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(d.get("company",""),d.get("role",""),d.get("city",""),d.get("degree",""),d.get("major",""),d.get("experience",""),d.get("salary",""),d.get("status","待核实"),d.get("url",""),d.get("description",""),d["match_score"],d.get("apply_status","待筛选"),d.get("applied_date",""),d.get("notes",""),d.get("source","手动录入")))
    c.commit();c.close()
def update_job_status(job_id,status,notes,applied_date):
    c=connect();c.execute("UPDATE jobs SET apply_status=?,notes=?,applied_date=? WHERE id=?",(status,notes,applied_date,job_id));c.commit();c.close()
def candidate_to_job(candidate):
    title=candidate.get("title","")
    # Conservative extraction: don't invent employer or specific role
    role=title[:180]
    city=candidate.get("city","")
    add_job({"company":"待核实","role":role,"city":city,"degree":"待核实","major":"应用化学/相关专业（待核实）","experience":"待核实","salary":"未公开/待核实","status":"待核实","url":candidate.get("url",""),"description":candidate.get("snippet",""),"apply_status":"待筛选","source":candidate.get("source","搜索候选")})

st.title("🎯 AI求职助手 · v1.0")
st.caption("面向应用化学本科应届生｜深圳、广州、上海｜自动搜索、岗位分析、材料准备、投递管理｜关键步骤人工确认")
with st.sidebar:
    st.header("🎓 求职目标")
    st.write("**城市：** 深圳 / 广州 / 上海")
    st.write("**学历：** 本科应届生")
    st.write("**专业：** 应用化学")
    st.write("**目标：** 分析检测、QC/质量、实验室、应用技术、工艺、材料/医药/半导体/新能源")
    st.info("搜索结果只是候选线索。投递前必须打开原始招聘页面核实职位、要求和状态。")
    st.caption("本版本不自动提交申请、不绕过招聘网站限制、不伪造信息。")

jobs=fetch_jobs(); candidates=fetch_candidates()
applied=int((jobs.get("apply_status",pd.Series(dtype=str))=="已投递").sum()) if len(jobs) else 0
m1,m2,m3,m4=st.columns(4)
m1.metric("已保存岗位",len(jobs));m2.metric("待筛选",int((jobs.get("apply_status",pd.Series(dtype=str))=="待筛选").sum()) if len(jobs) else 0);m3.metric("已投递",applied);m4.metric("搜索候选",len(candidates))
tabs=st.tabs(["🏠 工作台","🔎 自动搜索","➕ 添加岗位","📥 CSV导入/导出","🎯 岗位分析","📝 求职材料","📌 投递管理"])

with tabs[0]:
    st.subheader("岗位匹配度排名")
    if len(jobs):
        display=jobs[["company","role","city","degree","major","experience","salary","match_score","apply_status","url"]].copy()
        st.dataframe(display,use_container_width=True,hide_index=True)
    else:st.info("还没有保存岗位。先去“自动搜索”或“添加岗位”。")
    st.subheader("近期搜索候选")
    if len(candidates):
        st.dataframe(candidates[["title","city","match_score","source","url"]].head(20),use_container_width=True,hide_index=True)
    else:st.info("尚无搜索候选。")
    st.caption("匹配分数为规则初筛，不代表真实录取概率。")

with tabs[1]:
    st.subheader("自动搜索岗位")
    city=st.multiselect("搜索城市",PROFILE["cities"],default=PROFILE["cities"])
    terms=st.multiselect("搜索方向",SEARCH_TERMS,default=SEARCH_TERMS[:8])
    max_each=st.slider("每个搜索词最多保留结果",3,12,6)
    if st.button("🚀 开始搜索岗位",type="primary"):
        allrows=[]; progress=st.progress(0); total=max(1,len(city)*len(terms)); idx=0
        for cty in city:
            for term in terms:
                idx+=1; progress.progress(idx/total)
                q=f"{term} {cty} 本科 应届 招聘"
                try:allrows.extend(search_ddg(q,cty,max_each))
                except Exception as e:st.warning(f"搜索暂时失败：{q}（{str(e)[:120]}）")
        if allrows:
            save_candidates(allrows); st.success(f"搜索完成：发现 {len(allrows)} 条结果，已去重保存到候选列表。")
            st.rerun()
        else:st.warning("没有获取到结果。可稍后重试，或手动添加岗位。")
    cand=fetch_candidates()
    if len(cand):
        minscore=st.slider("最低初筛分数",0,100,50,key="cand_min")
        ccity=st.multiselect("候选城市筛选",PROFILE["cities"],default=PROFILE["cities"],key="cand_city")
        filtered=cand[(cand.match_score>=minscore)&(cand.city.isin(ccity))]
        st.dataframe(filtered[["title","city","match_score","fit_reasons","risk_flags","url"]],use_container_width=True,hide_index=True)
        if len(filtered):
            options={f"#{r.id}｜{r.city}｜{r.title[:70]}":int(r.id) for _,r in filtered.iterrows()}
            pick=st.selectbox("选择一个候选加入投递管理",list(options))
            if st.button("➕ 将候选保存为正式岗位记录"):
                row=filtered[filtered.id==options[pick]].iloc[0].to_dict();candidate_to_job(row);st.success("已添加到岗位管理，具体公司和要求仍需核实。");st.rerun()

with tabs[2]:
    st.subheader("手动录入岗位")
    with st.form("addjob"):
        company=st.text_input("公司名称")
        role=st.text_input("岗位名称")
        city=st.selectbox("城市",PROFILE["cities"])
        degree=st.text_input("学历要求",placeholder="本科 / 本科及以上 / 待核实")
        major=st.text_input("专业要求",placeholder="应用化学、化学、材料等")
        experience=st.text_input("经验要求",placeholder="应届 / 无经验 / 1-3年 / 待核实")
        salary=st.text_input("薪资",placeholder="如 8-12k/月；未公开可留空")
        status=st.selectbox("招聘状态",["招聘中（已核实）","待核实","已关闭"])
        url=st.text_input("招聘链接")
        description=st.text_area("职位描述/JD")
        notes=st.text_area("备注")
        submitted=st.form_submit_button("保存岗位")
    if submitted:
        if not company or not role:st.error("公司名称和岗位名称必填。")
        else:add_job({"company":company,"role":role,"city":city,"degree":degree,"major":major,"experience":experience,"salary":salary,"status":status,"url":url,"description":description,"notes":notes,"source":"手动录入"});st.success("岗位已保存！");st.rerun()

with tabs[3]:
    st.subheader("CSV导入 / 导出")
    if len(jobs):
        csvdata=jobs.to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇️ 导出全部岗位记录 CSV",csvdata,"job_tracker_export.csv","text/csv")
    else:st.info("暂无岗位记录可导出。")
    upload=st.file_uploader("导入岗位 CSV（列名尽量与导出文件一致）",type=["csv"])
    if upload is not None:
        try:
            imported=pd.read_csv(upload).fillna("")
            st.write("预览：");st.dataframe(imported.head(),use_container_width=True)
            if st.button("确认导入CSV"):
                c=connect()
                for _,r in imported.iterrows():
                    data={k:str(r.get(k,"")) for k in ["company","role","city","degree","major","experience","salary","status","url","description","apply_status","applied_date","notes","source"]}
                    data["apply_status"]=data.get("apply_status") or "待筛选"; data["source"]=data.get("source") or "CSV导入"; data["match_score"]=score_job(data)
                    c.execute("""INSERT INTO jobs(company,role,city,degree,major,experience,salary,status,url,description,match_score,apply_status,applied_date,notes,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    tuple(data.get(k,"") for k in ["company","role","city","degree","major","experience","salary","status","url","description"])+ (data["match_score"],data["apply_status"],data.get("applied_date",""),data.get("notes",""),data["source"]))
                c.commit();c.close();st.success(f"导入 {len(imported)} 条。");st.rerun()
        except Exception as e:st.error(f"CSV读取失败：{e}")

with tabs[4]:
    st.subheader("岗位分析与投递判断")
    if len(jobs):
        jopts={f"#{r.id}｜{r.company}｜{r.role}｜{r.city}":int(r.id) for _,r in jobs.iterrows()}
        chosen=st.selectbox("选择需要分析的岗位",list(jopts))
        row=jobs[jobs.id==jopts[chosen]].iloc[0]
        st.metric("规则匹配分数",f"{int(row.match_score)} / 100")
        st.write("**基础判断**")
        reasons=[]
        if row.city in PROFILE["cities"]:reasons.append("城市在你的目标范围内")
        if "本科" in str(row.degree) or "应届" in str(row.degree):reasons.append("学历/应届线索匹配")
        if any(k in str(row.major) for k in ["化学","应用化学","材料","化工"]):reasons.append("专业相关")
        if any(k in str(row.role) for k in PROFILE["keywords"]):reasons.append("岗位方向相关")
        st.write("；".join(reasons) or "现有信息不足，建议核实后再判断")
        st.warning("分析基于你录入的岗位信息，不会自动验证招聘是否仍开放。")
        st.write("**岗位信息**");st.write(f"学历：{row.degree or '未填写'}｜专业：{row.major or '未填写'}｜经验：{row.experience or '未填写'}｜薪资：{row.salary or '未公开'}")
        st.write("**建议**")
        if int(row.match_score)>=70:st.success("优先核实并准备投递。")
        elif int(row.match_score)>=50:st.info("可以投递，建议先确认学历、专业、经验和岗位内容。")
        else:st.warning("目前匹配较弱或信息不全，先核实关键要求。")
        if row.url:st.link_button("打开招聘原页面核实",row.url)
        st.text_area("职位描述",str(row.description),height=180)
    else:st.info("先添加或导入岗位，再进行分析。")

with tabs[5]:
    st.subheader("求职材料生成中心")
    resume=st.file_uploader("上传你的真实简历（仅用于本次页面生成提示词，不保存到数据库）",type=["pdf","docx"],key="resume_material")
    job_text=st.text_area("粘贴目标岗位JD",height=240)
    material_type=st.selectbox("生成材料类型",["岗位定制简历优化提示词","HR聊天开场白","求职邮件","自我介绍","面试准备清单"])
    if st.button("生成材料/提示词"):
        profile_text="学历：本科应届生；学校：广东海洋大学；专业：应用化学；目标城市：深圳、广州、上海。请严格根据用户提供的真实简历，不虚构经历、技能、成果、数据或项目。"
        if material_type=="岗位定制简历优化提示词":
            prompt=f"""请作为求职简历顾问，严格基于我的真实简历内容进行岗位针对性优化，不得编造或夸大。{profile_text}\n\n目标岗位JD：\n{job_text}\n\n请输出：1.匹配点 2.不足/缺失项 3.可调整的真实简历措辞 4.完整修改版简历 5.需要我确认的事实。"""
        elif material_type=="HR聊天开场白":
            prompt=f"请基于真实信息，写3版自然、不夸张的HR开场白，询问岗位是否接受应用化学本科应届生。个人信息：{profile_text}\n岗位JD：{job_text}"
        elif material_type=="求职邮件":
            prompt=f"请写一封针对岗位的求职邮件，简洁、专业，所有经历只来自真实简历，不编造。个人信息：{profile_text}\n岗位JD：{job_text}"
        elif material_type=="自我介绍":
            prompt=f"请基于真实简历和JD生成60秒、90秒两版面试自我介绍，标记需要本人确认的信息，不虚构。个人信息：{profile_text}\n岗位JD：{job_text}"
        else:
            prompt=f"请根据岗位JD为应用化学本科应届生准备面试题、参考回答框架、技术知识复习重点及反问问题。答案必须基于真实简历，缺少的信息用待本人补充标记。个人信息：{profile_text}\n岗位JD：{job_text}"
        st.text_area("复制下面内容到ChatGPT即可生成具体材料",prompt,height=300)
        st.caption("本工具当前提供低成本、可复制的提示词工作流，不调用收费AI API，也不自动把简历上传到第三方。")

with tabs[6]:
    st.subheader("投递状态管理")
    if len(jobs):
        jobopts={f"#{r.id}｜{r.company}｜{r.role}":int(r.id) for _,r in jobs.iterrows()}
        selected=st.selectbox("选择岗位",list(jobopts),key="tracker_select")
        r=jobs[jobs.id==jobopts[selected]].iloc[0]
        with st.form("tracker_update"):
            newstatus=st.selectbox("投递状态",STATUS_OPTIONS,index=STATUS_OPTIONS.index(r.apply_status) if r.apply_status in STATUS_OPTIONS else 0)
            applieddate=st.date_input("投递日期",value=date.fromisoformat(r.applied_date) if r.applied_date and str(r.applied_date)[:10] not in ["","None"] else date.today())
            newnotes=st.text_area("跟进记录/面试/HR回复",str(r.notes or ""))
            update=st.form_submit_button("更新投递记录")
        if update:
            update_job_status(int(r.id),newstatus,newnotes,applieddate.isoformat() if newstatus=="已投递" else (r.applied_date or ""));st.success("记录已更新。");st.rerun()
        if r.url:st.link_button("打开招聘页面",r.url)
        st.write("**提醒：** 每次状态更新后，建议在备注中记录日期、联系人、回复内容和下一步行动。")
    else:st.info("暂无岗位。")

st.divider()
st.caption("v1.0 | 岗位搜索结果需要人工核实 | 申请提交由本人确认 | 请勿上传身份证、银行卡、密码等敏感信息")

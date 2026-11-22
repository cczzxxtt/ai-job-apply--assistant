import streamlit as st
import pandas as pd
import sqlite3, json, re, time, urllib.parse
from datetime import date
from html.parser import HTMLParser
import requests

st.set_page_config(page_title='AI求职助手 v0.2', page_icon='🎯', layout='wide')
DB='jobs.db'
PROFILE={'cities':['深圳','广州','上海'],'degree':'本科应届生','major':'应用化学',
 'roles':['化学分析','分析检测','QC','质量','实验员','实验技术员','研究助理','应用工程师','技术支持','工艺工程师','工艺技术员'],
 'keywords':['化学','应用化学','分析化学','材料','化工','检测','实验','QC','质量','工艺','技术支持','研发']}
SEARCH_TERMS=['化学分析','分析检测','QC质量','实验员研究助理','应用工程师技术支持','工艺技术员']

class DDGParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.items=[]; self.current=None; self.capture=None; self.buf=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='a' and ('result__a' in a.get('class','')):
            self.current={'title':'','url':a.get('href',''),'snippet':''}; self.capture='title'; self.buf=[]
        elif tag in ('div','a') and self.current and ('result__snippet' in a.get('class','')):
            self.capture='snippet'; self.buf=[]
    def handle_data(self,data):
        if self.capture: self.buf.append(data)
    def handle_endtag(self,tag):
        if self.capture and tag in ('a','div'):
            text=' '.join(' '.join(self.buf).split())
            if self.capture=='title' and self.current: self.current['title']=text
            elif self.capture=='snippet' and self.current: self.current['snippet']=text
            self.capture=None; self.buf=[]
            if self.current and self.current.get('title'):
                self.items.append(self.current); self.current=None

def connect():
    c=sqlite3.connect(DB)
    c.execute('''CREATE TABLE IF NOT EXISTS jobs (
      id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT, role TEXT, city TEXT, degree TEXT, major TEXT,
      experience TEXT, salary TEXT, status TEXT, url TEXT, description TEXT, match_score INTEGER,
      apply_status TEXT, applied_date TEXT, notes TEXT, source TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS candidates (
      id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, url TEXT UNIQUE, snippet TEXT, city TEXT,
      query TEXT, source TEXT, match_score INTEGER, found_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    c.commit(); return c

def score_job(row):
    score=0; city=str(row.get('city',''))
    if any(c in city for c in PROFILE['cities']): score+=25
    degree=str(row.get('degree','')).lower()
    if '本科' in degree or '大专' in degree or '不限' in degree: score+=20
    elif '硕士' in degree or '博士' in degree: score-=30
    major=str(row.get('major',''))
    if any(k in major for k in ['应用化学','化学','材料','化工','理工']): score+=20
    role=str(row.get('role',''))
    if any(k in role for k in ['分析','检测','QC','质量','实验','技术员','研究助理']): score+=20
    elif any(k in role for k in ['应用','技术支持','工艺']): score+=15
    exp=str(row.get('experience',''))
    if '应届' in exp or '无经验' in exp or '不限' in exp: score+=15
    elif any(k in exp for k in ['3年','5年']): score-=20
    return max(0,min(100,score))

def fetch_jobs():
    c=connect(); df=pd.read_sql_query('SELECT * FROM jobs ORDER BY match_score DESC, id DESC',c); c.close(); return df

def fetch_candidates():
    c=connect(); df=pd.read_sql_query('SELECT * FROM candidates ORDER BY match_score DESC, found_at DESC',c); c.close(); return df

def add_job(data):
    data['match_score']=score_job(data); c=connect()
    c.execute('INSERT INTO jobs(company,role,city,degree,major,experience,salary,status,url,description,match_score,apply_status,applied_date,notes,source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
      (data.get('company',''),data.get('role',''),data.get('city',''),data.get('degree',''),data.get('major',''),data.get('experience',''),data.get('salary',''),data.get('status','待核实'),data.get('url',''),data.get('description',''),data['match_score'],data.get('apply_status','待筛选'),data.get('applied_date',''),data.get('notes',''),data.get('source','手动录入')))
    c.commit(); c.close()

def search_ddg(query, city, max_results=8):
    url='https://html.duckduckgo.com/html/?q='+urllib.parse.quote(query)
    headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36'}
    response=requests.get(url,headers=headers,timeout=18); response.raise_for_status()
    parser=DDGParser(); parser.feed(response.text)
    out=[]
    for item in parser.items[:max_results]:
        link=item.get('url','')
        if 'uddg=' in link:
            try: link=urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get('uddg',[link])[0]
            except Exception: pass
        if not link.startswith('http'): continue
        title=item.get('title',''); snippet=item.get('snippet','')
        text=(title+' '+snippet).lower()
        score=0
        if city in title or city in snippet: score+=25
        if any(k.lower() in text for k in ['化学','chemical','分析','检测','材料','qc','质量','实验','工艺']): score+=25
        if any(k in text for k in ['本科','应届','无经验','校招','毕业生']): score+=25
        if any(k in text for k in ['硕士','博士','3年以上','5年以上']): score-=25
        if any(k in text for k in ['深圳','广州','上海']): score+=15
        out.append({'title':title,'url':link,'snippet':snippet,'city':city,'query':query,'source':'DuckDuckGo搜索','match_score':max(0,min(100,score))})
    return out

def save_candidates(items):
    c=connect(); added=0
    for it in items:
        try:
            cur=c.execute('INSERT OR IGNORE INTO candidates(title,url,snippet,city,query,source,match_score) VALUES (?,?,?,?,?,?,?)',
              (it['title'],it['url'],it['snippet'],it['city'],it['query'],it['source'],it['match_score']))
            if cur.rowcount == 1: added+=1
        except Exception: pass
    c.commit(); c.close(); return added

st.title('🎯 AI求职助手 · v0.2')
st.caption('应用化学本科应届生｜深圳 · 广州 · 上海｜岗位搜索候选 + 匹配评分 + 投递跟踪｜申请提交仍由本人确认')
with st.sidebar:
    st.header('求职条件')
    st.write('**城市：** 深圳、广州、上海'); st.write('**学历：** 本科应届优先'); st.write('**专业：** 应用化学及相关专业')
    st.write('**目标方向：** 化学分析、检测、QC、实验技术、应用技术、工艺')
    st.warning('自动搜索为公开搜索引擎结果，结果可能重复、过期或不完整。打开原网页核实后再申请。')

pages=st.tabs(['📊 工作台','🔎 自动搜索','➕ 添加岗位','📥 CSV导入','📋 投递管理','📝 简历与话术'])
with pages[0]:
    df=fetch_jobs(); candidates=fetch_candidates()
    a,b,d,e=st.columns(4); a.metric('已保存岗位',len(df)); b.metric('待筛选',int((df.apply_status=='待筛选').sum()) if len(df) else 0); d.metric('已投递',int((df.apply_status=='已投递').sum()) if len(df) else 0); e.metric('搜索候选',len(candidates))
    if len(df):
        st.subheader('岗位匹配度排名'); st.dataframe(df[['company','role','city','degree','major','experience','salary','match_score','status','url','apply_status']],use_container_width=True,hide_index=True)
    else: st.info('还没有正式保存的岗位。请先自动搜索、手动添加或CSV导入。')
    if len(candidates): st.subheader('最近搜索候选'); st.dataframe(candidates[['title','city','match_score','source','url']],use_container_width=True,hide_index=True)
with pages[1]:
    st.subheader('公开招聘信息搜索（实验版）')
    st.write('通过公开搜索引擎查找招聘页面，不登录招聘网站、不自动提交申请。')
    cities=st.multiselect('搜索城市',PROFILE['cities'],default=PROFILE['cities'])
    role_terms=st.multiselect('岗位方向',SEARCH_TERMS,default=SEARCH_TERMS[:4])
    max_per=st.slider('每条搜索最多收集结果数',3,10,6)
    if st.button('🚀 开始搜索岗位',type='primary',disabled=not cities or not role_terms):
        all_items=[]; progress=st.progress(0); status_text=st.empty(); total=len(cities)*len(role_terms)
        for idx,(city,term) in enumerate([(c,t) for c in cities for t in role_terms],1):
            q=f'{city} {term} 招聘 应届 本科 应用化学'
            status_text.write(f'搜索中：{q}')
            try:
                found=search_ddg(q,city,max_per); all_items.extend(found)
            except Exception as ex:
                st.warning(f'搜索失败（{city}/{term}）：{str(ex)[:150]}')
            progress.progress(idx/total); time.sleep(0.8)
        n=save_candidates(all_items); st.success(f'搜索结束：获取 {len(all_items)} 条结果，其中新增保存 {n} 条。'); st.rerun()
    cand=fetch_candidates()
    if len(cand):
        st.subheader('候选岗位列表')
        st.caption('匹配分仅根据搜索标题/摘要初步估算。请核实招聘状态、公司、学历、专业、经验和申请链接。')
        view=cand.copy(); view['选择导入']=False
        edited=st.data_editor(view[['选择导入','title','city','match_score','snippet','url','query','found_at']],use_container_width=True,hide_index=True,disabled=['title','city','match_score','snippet','url','query','found_at'],column_config={'选择导入':st.column_config.CheckboxColumn(),'url':st.column_config.LinkColumn('招聘链接')})
        selected=edited[edited['选择导入']]
        if st.button('将选中候选加入投递管理',disabled=len(selected)==0):
            for _,r in selected.iterrows():
                add_job({'company':'待核实公司','role':r['title'],'city':r['city'],'degree':'待核实','major':'应用化学/化学/材料等（待核实）','experience':'待核实','salary':'','status':'待核实','url':r['url'],'description':r['snippet'],'source':'自动搜索候选：'+str(r['query'])})
            st.success(f'已将 {len(selected)} 条候选加入岗位库，状态标记为“待核实”。'); st.rerun()
        if st.button('清空候选搜索结果'):
            c=connect(); c.execute('DELETE FROM candidates'); c.commit(); c.close(); st.rerun()
    else: st.info('尚无候选搜索结果。点击上方“开始搜索岗位”进行搜索。')
with pages[2]:
    st.subheader('录入岗位信息')
    with st.form('job_form'):
        company=st.text_input('公司名称*'); role=st.text_input('岗位名称*'); city=st.selectbox('城市',['深圳','广州','上海','其他'])
        degree=st.text_input('学历要求',placeholder='本科及以上 / 本科 / 大专及以上'); major=st.text_input('专业要求',placeholder='应用化学、化学、材料等')
        experience=st.text_input('经验要求',placeholder='应届 / 无经验 / 1-3年'); salary=st.text_input('薪资'); status=st.selectbox('招聘状态',['待核实','招聘中','已截止','未知'])
        url=st.text_input('申请链接'); source=st.text_input('来源'); description=st.text_area('岗位描述/备注'); submit=st.form_submit_button('保存岗位')
        if submit:
            if not company or not role: st.error('公司名称和岗位名称必须填写。')
            else: add_job(locals()); st.success(f'岗位已保存，自动匹配分：{score_job(locals())}分'); st.rerun()
with pages[3]:
    st.subheader('CSV批量导入'); st.write('CSV列名建议：company, role, city, degree, major, experience, salary, status, url, description, source')
    template=pd.DataFrame(columns=['company','role','city','degree','major','experience','salary','status','url','description','source'])
    st.download_button('下载CSV模板',template.to_csv(index=False).encode('utf-8-sig'),'jobs_template.csv','text/csv')
    file=st.file_uploader('上传岗位CSV文件',type=['csv'])
    if file:
        imp=pd.read_csv(file).fillna(''); st.dataframe(imp.head(20),use_container_width=True)
        if st.button('导入这些岗位'):
            for _,r in imp.iterrows(): add_job(r.to_dict())
            st.success(f'已导入 {len(imp)} 条'); st.rerun()
with pages[4]:
    st.subheader('投递跟踪'); df=fetch_jobs()
    if len(df):
        selected=st.selectbox('选择岗位',df.apply(lambda r:f"#{r.id} {r.company}｜{r.role}｜{r.city}",axis=1)); jid=int(selected.split(' ')[0][1:]); row=df[df.id==jid].iloc[0]
        with st.form('update'):
            status=st.selectbox('投递状态',['待筛选','准备投递','已投递','笔试','面试','Offer','拒绝','已截止'],index=['待筛选','准备投递','已投递','笔试','面试','Offer','拒绝','已截止'].index(row.apply_status) if row.apply_status in ['待筛选','准备投递','已投递','笔试','面试','Offer','拒绝','已截止'] else 0)
            applied=st.date_input('投递日期',value=date.today() if row.applied_date=='' else pd.to_datetime(row.applied_date).date()); notes=st.text_area('跟进记录',value=row.notes)
            if st.form_submit_button('更新记录'):
                c=connect(); c.execute('UPDATE jobs SET apply_status=?,applied_date=?,notes=? WHERE id=?',(status,applied.isoformat(),notes,jid));c.commit();c.close();st.success('更新成功');st.rerun()
        st.markdown('**申请链接**');
        if row.url: st.link_button('打开招聘页面',row.url)
        st.download_button('导出投递记录CSV',df.to_csv(index=False).encode('utf-8-sig'),'application_tracker.csv','text/csv')
    else: st.info('先添加岗位后才能跟踪。')
with pages[5]:
    st.subheader('简历与申请话术'); resume=st.file_uploader('上传简历（仅当前运行环境处理；此版本不自动发送）',type=['docx','pdf'])
    st.write('**HR打招呼模板**'); st.text_area('复制使用',value='您好，我是广东海洋大学应用化学专业本科应届毕业生，关注贵公司的【岗位名称】岗位。希望有机会进一步沟通，谢谢！',height=150)
    st.warning('本版可搜索公开网页候选。下一版计划：AI岗位分析、简历定制、每日自动更新、浏览器辅助填写。最终申请由本人审核确认。')
st.divider(); st.caption('MVP v0.2｜公开搜索结果需人工核实；云端本地数据库可能不保证永久保存，请定期导出CSV备份。')

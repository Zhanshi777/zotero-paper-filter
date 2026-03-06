import feedparser
import os
import json
from datetime import datetime, timedelta
from urllib.parse import quote
import re
import html
import requests
import openai

# ==================== 配置区域 ====================

FEEDS = {
    "Nature": "https://www.nature.com/nature.rss",
    "Nature Communications": "https://www.nature.com/ncomms.rss",
    "Science": "https://feeds.science.org/rss/science.xml",
    "Joule": "https://www.cell.com/joule/inpress.rss",
    "Nature Energy": "https://www.nature.com/nenergy.rss",
    "Nature Synthesis": "https://www.nature.com/natsynth.rss",
    "Energy & Environmental Science": "http://feeds.rsc.org/rss/ee",
    "Angewandte Chemie": "https://onlinelibrary.wiley.com/feed/15213773/most-recent",
    "Advanced Materials": "https://advanced.onlinelibrary.wiley.com/feed/15214095/most-recent",
    "Advanced Energy Materials": "https://advanced.onlinelibrary.wiley.com/feed/16146840/most-recent",
    "Advanced Functional Materials": "https://advanced.onlinelibrary.wiley.com/feed/16163028/most-recent"
}

KEYWORDS_ENV = os.environ.get('RESEARCH_KEYWORDS', 'perovskite')
KEYWORDS = [k.strip().lower() for k in KEYWORDS_ENV.split(',') if k.strip()]

DAYS_BACK = 3

API_KEY = os.environ.get('OPENAI_API_KEY', '')
BASE_URL = os.environ.get('OPENAI_BASE_URL', None)

ai_client = None
if API_KEY:
    client_kwargs = {"api_key": API_KEY}
    if BASE_URL:
        client_kwargs["base_url"] = BASE_URL
    ai_client = openai.OpenAI(**client_kwargs)

# ==================== 核心函数 ====================

def clean_html(text):
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', '', text)
    clean = html.unescape(clean)
    return clean.strip()

def fetch_papers():
    all_papers = []
    cutoff_date = datetime.now() - timedelta(days=DAYS_BACK)
    
    print(f"正在抓取 {len(FEEDS)} 个期刊的RSS源...")
    print(f"筛选关键词: {', '.join(KEYWORDS)}")
    
    for journal, url in FEEDS.items():
        if not url:
            continue
            
        try:
            print(f"  📰 正在获取: {journal}")
            
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(url, timeout=30, headers=headers)
            response.raise_for_status()
            
            feed = feedparser.parse(response.content)
            
            for entry in feed.entries:
                try:
                    pub_date = None
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        pub_date = datetime(*entry.published_parsed[:6])
                    elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                        pub_date = datetime(*entry.updated_parsed[:6])
                    
                    if pub_date and pub_date < cutoff_date:
                        continue
                    
                    authors = "Unknown"
                    if hasattr(entry, 'authors') and entry.authors:
                        author_list = [a.get('name', '') for a in entry.authors if a.get('name')]
                        if author_list:
                            authors = ", ".join(author_list[:3])
                            if len(entry.authors) > 3:
                                authors += " et al."
                    elif hasattr(entry, 'author'):
                        authors = entry.author
                    
                    summary = ""
                    if hasattr(entry, 'summary'):
                        summary = clean_html(entry.summary)
                    elif hasattr(entry, 'description'):
                        summary = clean_html(entry.description)
                    
                    title = clean_html(entry.get('title', 'No Title'))
                    
                    paper = {
                        'title': title,
                        'link': entry.get('link', ''),
                        'summary': summary,
                        'published': pub_date.strftime('%Y-%m-%d') if pub_date else datetime.now().strftime('%Y-%m-%d'),
                        'authors': authors,
                        'journal': journal,
                        'matched_keywords': [],
                        'research_background': '',
                        'methodology': '',
                        'key_findings': '',
                        'theory_breakthrough': '',
                        'performance_breakthrough': ''
                    }
                    
                    all_papers.append(paper)
                    
                except Exception as e:
                    continue
                    
        except Exception as e:
            print(f"  ❌ 获取 {journal} 失败: {e}")
            continue
    
    all_papers.sort(key=lambda x: x['published'], reverse=True)
    print(f"\n✅ 总共获取到 {len(all_papers)} 篇文献")
    return all_papers

def filter_by_keywords(papers):
    if not papers:
        return []
    
    if not KEYWORDS:
        print("⚠️ 未设置关键词，返回所有文献")
        return papers
    
    print(f"\n🔍 第一步：关键词匹配（{len(KEYWORDS)}个关键词）...")
    filtered = []
    
    for paper in papers:
        text_to_search = (paper['title'] + ' ' + paper['summary']).lower()
        
        matched = []
        for keyword in KEYWORDS:
            if keyword in text_to_search:
                matched.append(keyword)
        
        if matched:
            paper['matched_keywords'] = matched
            filtered.append(paper)
    
    print(f"🎯 关键词筛选完成：{len(filtered)}/{len(papers)} 篇相关文献")
    return filtered

def analyze_innovation(papers):
    """AI深度解析：详细分析研究背景、方法、发现、突破"""
    if not papers:
        return []
    
    if not ai_client:
        print("⚠️ 未配置AI API，跳过深度解析")
        for paper in papers:
            paper['research_background'] = "未配置AI"
            paper['methodology'] = "请手动查看原文"
            paper['key_findings'] = "暂无分析"
            paper['theory_breakthrough'] = "暂无"
            paper['performance_breakthrough'] = "暂无"
        return papers
    
    print(f"\n🤖 第二步：AI深度解析（仅{len(papers)}篇）...")
    print(f"   使用API: {'DeepSeek' if BASE_URL else 'OpenAI'}")
    
    for i, paper in enumerate(papers, 1):
        print(f"  [{i}/{len(papers)}] AI分析: {paper['title'][:50]}...")
        
        # 更详细的Prompt，要求结构化输出
        prompt = f"""请详细分析这篇学术论文，按以下结构输出：

期刊：{paper['journal']}
标题：{paper['title']}
摘要：{paper['summary'][:1000]}

请按以下5个部分详细分析（每部分50-80字，要具体）：

1. 研究背景：该研究解决了什么科学/技术问题？现有方法的局限是什么？
2. 研究方法：采用了什么实验/理论方法？关键的技术路线或策略？
3. 核心发现：研究得出了什么重要结论？发现了什么新现象或新机制？
4. 理论突破：在理论认识、机理阐明或模型建立方面有什么创新？
5. 性能突破：具体的性能指标提升（如效率、稳定性、寿命等，带具体数值）

要求：
- 避免空泛描述，要有实质内容
- 性能突破部分必须带具体数据（如效率从X%提升到Y%）
- 理论突破要说明新认识或新机制"""

        try:
            response = ai_client.chat.completions.create(
                model="gpt-3.5-turbo" if not BASE_URL else "deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是资深的材料科学和能源领域专家，擅长深度解析学术论文的创新点和科学价值。"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=800,  # 增加token以获取详细回答
                temperature=0.5
            )
            
            result = response.choices[0].message.content.strip()
            
            # 解析结构化输出
            sections = {
                '研究背景': 'research_background',
                '研究方法': 'methodology', 
                '核心发现': 'key_findings',
                '理论突破': 'theory_breakthrough',
                '性能突破': 'performance_breakthrough'
            }
            
            current_section = None
            content_buffer = []
            
            for line in result.split('\n'):
                line = line.strip()
                if not line:
                    continue
                    
                # 检查是否是章节标题
                for cn_title, en_key in sections.items():
                    if cn_title in line and ('：' in line or ':' in line or line.startswith(f"{cn_title}")):
                        # 保存上一个章节的内容
                        if current_section and content_buffer:
                            paper[current_section] = ' '.join(content_buffer).strip()
                        # 开始新章节
                        current_section = en_key
                        content_buffer = []
                        # 提取当前行的内容（去掉标题部分）
                        if '：' in line:
                            content = line.split('：', 1)[1].strip()
                            if content:
                                content_buffer.append(content)
                        break
                else:
                    # 不是标题，是内容
                    if current_section:
                        content_buffer.append(line)
            
            # 保存最后一个章节
            if current_section and content_buffer:
                paper[current_section] = ' '.join(content_buffer).strip()
            
            # 确保所有字段都有值
            for key in sections.values():
                if not paper.get(key):
                    paper[key] = "详见原文"
            
            print(f"      ✅ 解析完成")
            
        except Exception as e:
            print(f"      ⚠️ AI解析失败: {e}")
            paper['research_background'] = "AI解析失败"
            paper['methodology'] = "请查看原文"
            paper['key_findings'] = "解析失败"
            paper['theory_breakthrough'] = "暂无"
            paper['performance_breakthrough'] = "暂无"
    
    print(f"\n✅ AI深度解析完成：共处理{len(papers)}篇")
    return papers

def generate_html(papers):
    today = datetime.now().strftime('%Y-%m-%d')
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>文献日报 - {today}</title>
    <style>
        :root {{
            --primary: #667eea;
            --secondary: #764ba2;
            --accent: #48bb78;
            --warning: #ed8936;
            --info: #4299e1;
            --bg: #f7fafc;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            max-width: 1100px;
            margin: 0 auto;
            padding: 20px;
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            min-height: 100vh;
            line-height: 1.6;
        }}
        .container {{
            background: white;
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2d3748;
            text-align: center;
            margin-bottom: 10px;
            font-size: 32px;
        }}
        .subtitle {{
            text-align: center;
            color: #718096;
            margin-bottom: 30px;
            font-size: 16px;
        }}
        .stats {{
            background: linear-gradient(135deg, var(--primary), var(--secondary));
            color: white;
            padding: 20px;
            border-radius: 12px;
            margin-bottom: 40px;
            text-align: center;
            font-size: 15px;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
        }}
        .stats strong {{
            color: #ffd700;
        }}
        .paper {{
            border: 1px solid #e2e8f0;
            padding: 30px;
            margin: 30px 0;
            background: white;
            border-radius: 16px;
            transition: all 0.3s ease;
            position: relative;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        }}
        .paper:hover {{
            transform: translateY(-5px);
            box-shadow: 0 8px 30px rgba(0,0,0,0.12);
            border-color: var(--primary);
        }}
        .paper-header {{
            border-bottom: 2px solid #edf2f7;
            padding-bottom: 20px;
            margin-bottom: 20px;
        }}
        .paper-title {{
            font-size: 22px;
            font-weight: 700;
            color: #2d3748;
            margin-bottom: 12px;
            line-height: 1.4;
        }}
        .paper-title a {{
            color: var(--primary);
            text-decoration: none;
            transition: color 0.2s;
        }}
        .paper-title a:hover {{
            color: var(--secondary);
            text-decoration: underline;
        }}
        .paper-meta {{
            color: #4a5568;
            font-size: 14px;
            margin-bottom: 15px;
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
            align-items: center;
        }}
        .meta-item {{
            display: flex;
            align-items: center;
            gap: 5px;
        }}
        .tags {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 10px;
        }}
        .journal-tag {{
            display: inline-block;
            background: #e53e3e;
            color: white;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 600;
        }}
        .keyword-tag {{
            display: inline-block;
            background: var(--accent);
            color: white;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 500;
        }}
        
        /* Abstract部分 */
        .abstract-section {{
            background: #f8fafc;
            border-left: 4px solid var(--info);
            padding: 20px;
            margin: 20px 0;
            border-radius: 0 8px 8px 0;
        }}
        .abstract-title {{
            font-weight: 700;
            color: var(--info);
            font-size: 14px;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .abstract-content {{
            color: #4a5568;
            font-size: 15px;
            line-height: 1.8;
            text-align: justify;
        }}
        
        /* AI分析部分 */
        .ai-analysis {{
            background: linear-gradient(135deg, #faf5ff 0%, #f0fff4 100%);
            border: 2px solid #e2e8f0;
            border-radius: 12px;
            padding: 25px;
            margin-top: 25px;
        }}
        .ai-title {{
            font-size: 18px;
            font-weight: 700;
            color: #2d3748;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
            padding-bottom: 10px;
            border-bottom: 2px solid #e2e8f0;
        }}
        .ai-section {{
            margin-bottom: 18px;
            padding-bottom: 18px;
            border-bottom: 1px dashed #e2e8f0;
        }}
        .ai-section:last-child {{
            border-bottom: none;
            margin-bottom: 0;
            padding-bottom: 0;
        }}
        .ai-section-title {{
            font-weight: 700;
            font-size: 14px;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .ai-section-content {{
            color: #2d3748;
            font-size: 15px;
            line-height: 1.7;
            padding-left: 28px;
        }}
        
        /* 不同部分的配色 */
        .bg-research {{ color: #805ad5; }}  /* 紫色 - 背景 */
        .bg-method {{ color: #3182ce; }}    /* 蓝色 - 方法 */
        .bg-finding {{ color: #38a169; }}   /* 绿色 - 发现 */
        .bg-theory {{ color: #d69e2e; }}    /* 黄色 - 理论 */
        .bg-performance {{ color: #e53e3e; }} /* 红色 - 性能 */
        
        .add-btn {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            margin-top: 20px;
            background: linear-gradient(135deg, var(--primary), var(--secondary));
            color: white;
            padding: 12px 24px;
            border-radius: 8px;
            text-decoration: none;
            font-size: 15px;
            font-weight: 600;
            transition: all 0.3s;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
        }}
        .add-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.6);
        }}
        .empty {{
            text-align: center;
            padding: 80px 40px;
            color: #718096;
            font-size: 18px;
        }}
        .footer {{
            text-align: center;
            margin-top: 50px;
            padding-top: 30px;
            border-top: 2px solid #e2e8f0;
            color: #a0aec0;
            font-size: 13px;
        }}
        .ai-badge {{
            position: absolute;
            top: 20px;
            right: 20px;
            background: linear-gradient(135deg, var(--primary), var(--secondary));
            color: white;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 700;
            box-shadow: 0 2px 10px rgba(102, 126, 234, 0.4);
        }}
        mark {{
            background: linear-gradient(120deg, #fef3c7 0%, #fef3c7 100%);
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 600;
            color: #92400e;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📚 今日文献精选</h1>
        <div class="subtitle">智能筛选 · 深度解析 · 一键收藏</div>
        
        <div class="stats">
            <strong>筛选模式：</strong>关键词匹配 + AI深度解析 | 
            <strong>关键词：</strong>{', '.join(KEYWORDS)} | 
            <strong>精选文献：</strong>{len(papers)}篇 | 
            <strong>来源：</strong>{len(FEEDS)}个顶刊
        </div>
"""
    
    if not papers:
        html += '<div class="empty">今日暂无匹配文献<br><small>建议更换关键词或扩大时间范围</small></div>'
    else:
        for paper in papers:
            zotero_link = f"https://www.zotero.org/save?url={quote(paper['link'])}&title={quote(paper['title'])}"
            
            # 高亮关键词
            display_title = paper['title']
            for kw in paper.get('matched_keywords', []):
                pattern = re.compile(re.escape(kw), re.IGNORECASE)
                display_title = pattern.sub(f'<mark>{kw}</mark>', display_title)
            
            # 构建AI分析HTML
            ai_html = ""
            sections_data = [
                ('📋', '研究背景', 'bg-research', paper.get('research_background', '')),
                ('🔬', '研究方法', 'bg-method', paper.get('methodology', '')),
                ('💡', '核心发现', 'bg-finding', paper.get('key_findings', '')),
                ('📐', '理论突破', 'bg-theory', paper.get('theory_breakthrough', '')),
                ('📈', '性能突破', 'bg-performance', paper.get('performance_breakthrough', ''))
            ]
            
            for icon, title, css_class, content in sections_data:
                if content and content != "详见原文" and content != "AI解析失败":
                    ai_html += f"""
                <div class="ai-section">
                    <div class="ai-section-title {css_class}">{icon} {title}</div>
                    <div class="ai-section-content">{content}</div>
                </div>"""
            
            html += f"""
        <div class="paper">
            <div class="ai-badge">AI深度解析</div>
            
            <div class="paper-header">
                <div class="paper-title">
                    <a href="{paper['link']}" target="_blank">{display_title}</a>
                </div>
                <div class="paper-meta">
                    <span class="meta-item">👤 {paper['authors']}</span>
                    <span class="meta-item">📅 {paper['published']}</span>
                    <span class="meta-item">📰 {paper['journal']}</span>
                </div>
                <div class="tags">
                    <span class="journal-tag">{paper['journal']}</span>
                    {"".join([f'<span class="keyword-tag">{k}</span>' for k in paper.get('matched_keywords', [])])}
                </div>
            </div>
            
            <div class="abstract-section">
                <div class="abstract-title">📝 原文摘要（Abstract）</div>
                <div class="abstract-content">{paper['summary']}</div>
            </div>
            
            <div class="ai-analysis">
                <div class="ai-title">🔍 AI深度解读</div>
                {ai_html if ai_html else '<div style="color:#718096;text-align:center;padding:20px;">AI解析加载中...</div>'}
            </div>
            
            <a href="{zotero_link}" class="add-btn" target="_blank">
                <span>➕</span>
                <span>添加到Zotero</span>
            </a>
        </div>
"""
    
    html += f"""
        <div class="footer">
            <p>自动生成于 {today} | 关键词筛选 + {'DeepSeek' if BASE_URL else 'OpenAI'} AI深度解析</p>
            <p style="margin-top:10px;font-size:12px;">本页面由GitHub Actions自动生成，每日更新</p>
        </div>
    </div>
</body>
</html>
"""
    
    os.makedirs('docs', exist_ok=True)
    with open('docs/index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    
    with open('docs/papers.json', 'w', encoding='utf-8') as f:
        json.dump({
            'date': today,
            'keywords': KEYWORDS,
            'count': len(papers),
            'papers': papers
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 网页已生成：docs/index.html（{len(papers)}篇文献）")

if __name__ == '__main__':
    try:
        papers = fetch_papers()
        filtered = filter_by_keywords(papers)
        analyzed = analyze_innovation(filtered)
        generate_html(analyzed)
        print("\n🎉 全部完成！")
    except Exception as e:
        print(f"\n❌ 程序运行失败: {e}")
        import traceback
        traceback.print_exc()
        exit(1)

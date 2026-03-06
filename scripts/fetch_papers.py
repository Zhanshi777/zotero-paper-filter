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

# 关键词配置（用于第一步快速筛选）
KEYWORDS_ENV = os.environ.get('RESEARCH_KEYWORDS', 'perovskite')
KEYWORDS = [k.strip().lower() for k in KEYWORDS_ENV.split(',') if k.strip()]

DAYS_BACK = 3

# AI配置（用于第二步深度解析）
API_KEY = os.environ.get('OPENAI_API_KEY', '')
BASE_URL = os.environ.get('OPENAI_BASE_URL', None)

# 初始化AI客户端
ai_client = None
if API_KEY:
    client_kwargs = {"api_key": API_KEY}
    if BASE_URL:
        client_kwargs["base_url"] = BASE_URL
    ai_client = openai.OpenAI(**client_kwargs)

# ==================== 核心函数 ====================

def clean_html(text):
    """清理HTML标签"""
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', '', text)
    clean = html.unescape(clean)
    return clean.strip()

def fetch_papers():
    """从所有RSS源获取最近文献"""
    all_papers = []
    cutoff_date = datetime.now() - timedelta(days=DAYS_BACK)
    
    print(f"正在抓取 {len(FEEDS)} 个期刊的RSS源...")
    print(f"筛选关键词: {', '.join(KEYWORDS)}")
    
    for journal, url in FEEDS.items():
        if not url:
            continue
            
        try:
            print(f"  📰 正在获取: {journal}")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
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
                        'summary': summary[:1000] if summary else '',
                        'published': pub_date.strftime('%Y-%m-%d') if pub_date else datetime.now().strftime('%Y-%m-%d'),
                        'authors': authors,
                        'journal': journal,
                        'matched_keywords': [],
                        'innovation': '',  # AI分析的创新点
                        'breakthrough': ''  # 突破性描述
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
    """第一步：关键词快速筛选"""
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

def analyze_with_ai(papers):
    """第二步：AI深度解析创新点（只处理筛选后的文献）"""
    if not papers:
        return []
    
    if not ai_client:
        print("⚠️ 未配置AI API，跳过深度解析")
        for paper in papers:
            paper['innovation'] = "（未配置AI，无法生成创新点分析）"
            paper['breakthrough'] = "请先配置OpenAI API Key"
        return papers
    
    print(f"\n🤖 第二步：AI深度解析创新点（共{len(papers)}篇）...")
    print(f"   使用API: {'DeepSeek' if BASE_URL else 'OpenAI'}")
    
    for i, paper in enumerate(papers, 1):
        print(f"  [{i}/{len(papers)}] AI分析: {paper['title'][:50]}...")
        
        prompt = f"""请分析这篇学术论文的创新点和突破性，用一句话概括：

期刊：{paper['journal']}
标题：{paper['title']}
摘要：{paper['summary'][:800]}

请按以下格式回复：
创新点：（一句话描述核心创新，30-50字）
突破性：（说明相比现有工作的主要突破或优势，30-50字）

要求：
1. 简洁明了，突出核心创新
2. 具体说明技术突破或性能提升
3. 避免空泛的描述"""

        try:
            response = ai_client.chat.completions.create(
                model="gpt-3.5-turbo" if not BASE_URL else "deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是专业的学术论文分析专家，擅长提炼创新点和突破性成果。"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=200,
                temperature=0.7
            )
            
            result = response.choices[0].message.content.strip()
            
            # 解析AI返回的内容
            innovation = ""
            breakthrough = ""
            
            for line in result.split('\n'):
                if line.startswith('创新点：') or line.startswith('创新点:'):
                    innovation = line.split('：', 1)[1].strip() if '：' in line else line.split(':', 1)[1].strip()
                elif line.startswith('突破性：') or line.startswith('突破性:'):
                    breakthrough = line.split('：', 1)[1].strip() if '：' in line else line.split(':', 1)[1].strip()
            
            # 如果没解析到格式，用整段话作为创新点
            if not innovation:
                innovation = result[:100] + "..." if len(result) > 100 else result
            
            paper['innovation'] = innovation
            paper['breakthrough'] = breakthrough if breakthrough else "显著提升相关性能"
            
            print(f"      ✅ 解析完成")
            
        except Exception as e:
            print(f"      ⚠️ AI解析失败: {e}")
            paper['innovation'] = "（AI解析失败）"
            paper['breakthrough'] = "请查看原文获取详细信息"
    
    print(f"\n✅ AI深度解析完成")
    return papers

def generate_html(papers):
    """生成HTML网页"""
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
            --bg: #f7fafc;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1000px;
            margin: 0 auto;
            padding: 20px;
            background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%);
            min-height: 100vh;
        }}
        .container {{
            background: white;
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }}
        h1 {{
            color: #333;
            text-align: center;
            margin-bottom: 10px;
        }}
        .subtitle {{
            text-align: center;
            color: #666;
            margin-bottom: 20px;
        }}
        .stats {{
            background: var(--bg);
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 30px;
            text-align: center;
            font-size: 14px;
            border-left: 4px solid var(--accent);
        }}
        .paper {{
            border-left: 4px solid var(--primary);
            padding: 25px;
            margin: 25px 0;
            background: var(--bg);
            border-radius: 0 15px 15px 0;
            transition: all 0.3s ease;
            position: relative;
        }}
        .paper:hover {{
            transform: translateX(8px);
            box-shadow: 0 8px 25px rgba(0,0,0,0.15);
        }}
        .paper-title {{
            font-size: 20px;
            font-weight: bold;
            color: #2d3748;
            margin-bottom: 10px;
            line-height: 1.4;
        }}
        .paper-title a {{
            color: var(--primary);
            text-decoration: none;
        }}
        .paper-title a:hover {{
            text-decoration: underline;
        }}
        .paper-meta {{
            color: #718096;
            font-size: 13px;
            margin-bottom: 12px;
        }}
        .tags {{
            margin-bottom: 15px;
        }}
        .journal-tag {{
            display: inline-block;
            background: #e53e3e;
            color: white;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            margin-right: 8px;
            font-weight: 600;
        }}
        .keyword-tag {{
            display: inline-block;
            background: var(--accent);
            color: white;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            margin-right: 6px;
        }}
        .ai-analysis {{
            background: white;
            border: 2px solid #e2e8f0;
            border-radius: 10px;
            padding: 15px;
            margin-top: 15px;
        }}
        .innovation-box {{
            margin-bottom: 12px;
        }}
        .innovation-title {{
            font-weight: bold;
            color: var(--primary);
            font-size: 14px;
            margin-bottom: 5px;
            display: flex;
            align-items: center;
        }}
        .innovation-title::before {{
            content: "💡";
            margin-right: 6px;
        }}
        .innovation-content {{
            color: #2d3748;
            font-size: 15px;
            line-height: 1.6;
            padding-left: 24px;
        }}
        .breakthrough-box {{
            border-top: 1px solid #e2e8f0;
            padding-top: 12px;
            margin-top: 12px;
        }}
        .breakthrough-title {{
            font-weight: bold;
            color: var(--warning);
            font-size: 14px;
            margin-bottom: 5px;
            display: flex;
            align-items: center;
        }}
        .breakthrough-title::before {{
            content: "🚀";
            margin-right: 6px;
        }}
        .breakthrough-content {{
            color: #744210;
            font-size: 14px;
            line-height: 1.5;
            padding-left: 24px;
        }}
        .abstract {{
            color: #4a5568;
            font-size: 14px;
            line-height: 1.6;
            margin: 15px 0;
            padding: 10px;
            background: rgba(255,255,255,0.5);
            border-radius: 5px;
            max-height: 80px;
            overflow: hidden;
            position: relative;
        }}
        .abstract::after {{
            content: "...";
            position: absolute;
            bottom: 0;
            right: 0;
            background: linear-gradient(transparent, rgba(255,255,255,0.8));
            padding: 0 5px;
        }}
        .add-btn {{
            display: inline-block;
            margin-top: 15px;
            background: #3182ce;
            color: white;
            padding: 8px 20px;
            border-radius: 6px;
            text-decoration: none;
            font-size: 14px;
            font-weight: 600;
            transition: background 0.2s;
        }}
        .add-btn:hover {{
            background: #2c5282;
        }}
        .empty {{
            text-align: center;
            padding: 60px;
            color: #718096;
        }}
        .footer {{
            text-align: center;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #e2e8f0;
            color: #a0aec0;
            font-size: 12px;
        }}
        .ai-badge {{
            position: absolute;
            top: 15px;
            right: 15px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: bold;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📚 今日文献精选</h1>
        <div class="subtitle">{today}</div>
        
        <div class="stats">
            <strong>筛选模式：</strong>关键词匹配 + AI深度解析 | 
            <strong>关键词：</strong>{', '.join(KEYWORDS)} | 
            <strong>精选文献：</strong>{len(papers)}篇
        </div>
"""
    
    if not papers:
        html += '<div class="empty">今日暂无匹配文献<br><small>换个关键词试试？</small></div>'
    else:
        for paper in papers:
            zotero_link = f"https://www.zotero.org/save?url={quote(paper['link'])}&title={quote(paper['title'])}"
            
            # 高亮关键词
            display_title = paper['title']
            for kw in paper.get('matched_keywords', []):
                pattern = re.compile(re.escape(kw), re.IGNORECASE)
                display_title = pattern.sub(f'<mark style="background:#fef3c7;padding:2px 4px;border-radius:3px;">{kw}</mark>', display_title)
            
            # AI分析内容
            innovation_html = f"""
                <div class="innovation-box">
                    <div class="innovation-title">核心创新点</div>
                    <div class="innovation-content">{paper.get('innovation', '暂无分析')}</div>
                </div>
            """ if paper.get('innovation') else ""
            
            breakthrough_html = f"""
                <div class="breakthrough-box">
                    <div class="breakthrough-title">主要突破</div>
                    <div class="breakthrough-content">{paper.get('breakthrough', '')}</div>
                </div>
            """ if paper.get('breakthrough') else ""
            
            html += f"""
        <div class="paper">
            <div class="ai-badge">AI解析</div>
            <div class="paper-title">
                <a href="{paper['link']}" target="_blank">{display_title}</a>
            </div>
            <div class="paper-meta">
                👤 {paper['authors']} | 📅 {paper['published']} | 📰 {paper['journal']}
            </div>
            <div class="tags">
                <span class="journal-tag">{paper['journal']}</span>
                {"".join([f'<span class="keyword-tag">{k}</span>' for k in paper.get('matched_keywords', [])])}
            </div>
            <div class="abstract">{paper['summary'][:200]}...</div>
            
            <div class="ai-analysis">
                {innovation_html}
                {breakthrough_html}
            </div>
            
            <a href="{zotero_link}" class="add-btn" target="_blank">➕ 添加到Zotero</a>
        </div>
"""
    
    html += f"""
        <div class="footer">
            自动生成于 {today} | 关键词筛选 + {'DeepSeek' if BASE_URL else 'OpenAI'} AI解析
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
        # 第一步：获取文献
        papers = fetch_papers()
        
        # 第二步：关键词快速筛选
        filtered = filter_by_keywords(papers)
        
        # 第三步：AI深度解析（只对筛选后的少量文献）
        analyzed = analyze_with_ai(filtered)
        
        # 生成网页
        generate_html(analyzed)
        print("\n🎉 全部完成！")
        
    except Exception as e:
        print(f"\n❌ 程序运行失败: {e}")
        import traceback
        traceback.print_exc()
        exit(1)

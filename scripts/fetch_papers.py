import feedparser
import os
import json
from datetime import datetime, timedelta
import openai
from urllib.parse import quote
import re
import html
import requests

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

TOPICS_ENV = os.environ.get('RESEARCH_TOPICS', 'battery, energy storage, materials science, catalysis')
TOPICS = [t.strip() for t in TOPICS_ENV.split(',') if t.strip()]

# API配置 - 同时支持OpenAI和DeepSeek
API_KEY = os.environ.get('OPENAI_API_KEY', '')
# DeepSeek用户需要设置这个环境变量：https://api.deepseek.com
BASE_URL = os.environ.get('OPENAI_BASE_URL', None)  

DAYS_BACK = 3

# 初始化OpenAI客户端（v1.0+新方式）
client = None
if API_KEY:
    client_kwargs = {"api_key": API_KEY}
    if BASE_URL:
        client_kwargs["base_url"] = BASE_URL
    client = openai.OpenAI(**client_kwargs)

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
    print(f"关注主题: {', '.join(TOPICS)}")
    
    for journal, url in FEEDS.items():
        if not url:
            print(f"  ⚠️ {journal} 的URL为空，跳过")
            continue
            
        try:
            print(f"  📰 正在获取: {journal}")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, timeout=30, headers=headers)
            response.raise_for_status()
            
            feed = feedparser.parse(response.content)
            
            if feed.bozo:
                print(f"    ⚠️ 解析警告: {feed.bozo_exception}")
            
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
                    
                    paper = {
                        'title': clean_html(entry.get('title', 'No Title')),
                        'link': entry.get('link', ''),
                        'summary': summary[:800] if summary else '',
                        'published': pub_date.strftime('%Y-%m-%d') if pub_date else datetime.now().strftime('%Y-%m-%d'),
                        'authors': authors,
                        'journal': journal
                    }
                    
                    all_papers.append(paper)
                    
                except Exception as e:
                    print(f"    ⚠️ 处理单篇文献出错: {e}")
                    continue
                    
        except requests.exceptions.Timeout:
            print(f"  ⏱️ 获取 {journal} 超时（30秒）")
        except requests.exceptions.RequestException as e:
            print(f"  ❌ 获取 {journal} 网络错误: {e}")
        except Exception as e:
            print(f"  ❌ 获取 {journal} 失败: {e}")
            continue
    
    all_papers.sort(key=lambda x: x['published'], reverse=True)
    print(f"\n✅ 总共获取到 {len(all_papers)} 篇最近{DAYS_BACK}天的文献")
    return all_papers

def filter_by_ai(papers):
    """使用AI筛选相关文献"""
    if not papers:
        print("没有文献需要筛选")
        return []
    
    if not client:
        print("⚠️ 未设置API Key，跳过AI筛选，返回所有文献")
        return papers
    
    print(f"\n🤖 AI正在筛选文献（关注主题: {', '.join(TOPICS)}）...")
    print(f"   使用API: {'DeepSeek' if BASE_URL else 'OpenAI'}")
    filtered = []
    
    for i, paper in enumerate(papers, 1):
        print(f"  [{i}/{len(papers)}] {paper['title'][:60]}...")
        
        prompt = f"""判断这篇论文是否与以下研究主题相关：{', '.join(TOPICS)}

期刊：{paper['journal']}
标题：{paper['title']}
摘要：{paper['summary'][:500]}

如果相关，回复：RELEVANT|匹配主题|推荐理由（20字内）
如果不相关，回复：NOT_RELEVANT"""

        try:
            # 新版OpenAI API调用方式（兼容DeepSeek）
            response = client.chat.completions.create(
                model="gpt-3.5-turbo" if not BASE_URL else "deepseek-chat",  # DeepSeek使用deepseek-chat模型
                messages=[
                    {"role": "system", "content": "你是专业的学术文献筛选助手"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=100,
                temperature=0.3
            )
            
            result = response.choices[0].message.content.strip()
            
            if result.startswith('RELEVANT'):
                parts = result.split('|')
                paper['matched_topic'] = parts[1].strip() if len(parts) > 1 else 'General'
                paper['recommendation'] = parts[2].strip() if len(parts) > 2 else 'Related research'
                paper['relevance_score'] = 90
                filtered.append(paper)
                print(f"      ✅ 相关: {paper['matched_topic']}")
            else:
                print(f"      ❌ 不相关")
                
        except Exception as e:
            print(f"      ⚠️ AI错误: {e}")
            # 出错时默认保留，避免漏掉重要文献
            paper['matched_topic'] = 'AI Error - Manual Review'
            paper['recommendation'] = 'Please check manually'
            paper['relevance_score'] = 50
            filtered.append(paper)
    
    print(f"\n🎯 筛选完成：{len(filtered)}/{len(papers)} 篇相关")
    return filtered

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
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
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
            background: #f0f4f8;
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 30px;
            text-align: center;
            font-size: 14px;
        }}
        .paper {{
            border-left: 4px solid #667eea;
            padding: 20px;
            margin: 20px 0;
            background: #f8f9fa;
            border-radius: 0 10px 10px 0;
            transition: transform 0.2s;
        }}
        .paper:hover {{
            transform: translateX(5px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }}
        .paper-title {{
            font-size: 18px;
            font-weight: bold;
            color: #2d3748;
            margin-bottom: 8px;
            line-height: 1.4;
        }}
        .paper-title a {{
            color: #667eea;
            text-decoration: none;
        }}
        .paper-title a:hover {{
            text-decoration: underline;
        }}
        .paper-meta {{
            color: #718096;
            font-size: 13px;
            margin-bottom: 10px;
        }}
        .journal-tag {{
            display: inline-block;
            background: #e53e3e;
            color: white;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            margin-right: 8px;
            margin-bottom: 8px;
        }}
        .topic-tag {{
            display: inline-block;
            background: #48bb78;
            color: white;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            margin-bottom: 8px;
        }}
        .abstract {{
            color: #4a5568;
            font-size: 14px;
            line-height: 1.6;
            margin-top: 10px;
            max-height: 100px;
            overflow: hidden;
            position: relative;
        }}
        .recommendation {{
            background: #fff;
            border-left: 3px solid #48bb78;
            padding: 10px;
            margin-top: 10px;
            font-size: 13px;
            color: #2d3748;
            font-style: italic;
        }}
        .add-btn {{
            display: inline-block;
            margin-top: 10px;
            background: #3182ce;
            color: white;
            padding: 6px 16px;
            border-radius: 5px;
            text-decoration: none;
            font-size: 13px;
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
    </style>
</head>
<body>
    <div class="container">
        <h1>📚 今日文献精选</h1>
        <div class="subtitle">{today}</div>
        
        <div class="stats">
            <strong>关注领域：</strong>{', '.join(TOPICS)} | 
            <strong>今日更新：</strong>{len(papers)}篇 | 
            <strong>来源：</strong>{len(FEEDS)}个顶级期刊
        </div>
"""
    
    if not papers:
        html += '<div class="empty">今日暂无相关文献更新</div>'
    else:
        for paper in papers:
            zotero_link = f"https://www.zotero.org/save?url={quote(paper['link'])}&title={quote(paper['title'])}"
            
            html += f"""
        <div class="paper">
            <div class="paper-title">
                <a href="{paper['link']}" target="_blank">{paper['title']}</a>
            </div>
            <div class="paper-meta">
                👤 {paper['authors']} | 📅 {paper['published']} | 📰 {paper['journal']}
            </div>
            <div>
                <span class="journal-tag">{paper['journal']}</span>
                <span class="topic-tag">🏷️ {paper.get('matched_topic', 'General')}</span>
            </div>
            <div class="abstract">{paper['summary'][:300]}...</div>
            <div class="recommendation">💡 {paper.get('recommendation', 'Related to your research')}</div>
            <a href="{zotero_link}" class="add-btn" target="_blank">➕ 添加到Zotero</a>
        </div>
"""
    
    html += f"""
        <div class="footer">
            自动生成于 {today} | GitHub Actions + {'DeepSeek' if BASE_URL else 'OpenAI'}
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
            'topics': TOPICS,
            'count': len(papers),
            'papers': papers
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 网页已生成：docs/index.html（{len(papers)}篇文献）")

if __name__ == '__main__':
    try:
        papers = fetch_papers()
        filtered = filter_by_ai(papers)
        generate_html(filtered)
        print("\n🎉 全部完成！")
    except Exception as e:
        print(f"\n❌ 程序运行失败: {e}")
        import traceback
        traceback.print_exc()
        exit(1)

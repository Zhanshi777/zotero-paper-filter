import feedparser
import os
import json
from datetime import datetime
import openai
from urllib.parse import quote

# 配置
RSS_URL = os.environ.get('ZOTERO_RSS_URL')
TOPICS = os.environ.get('RESEARCH_TOPICS', 'machine learning, AI').split(',')
openai.api_key = os.environ.get('OPENAI_API_KEY')

def fetch_papers():
    """从Zotero RSS获取文献"""
    feed = feedparser.parse(RSS_URL)
    papers = []
    
    for entry in feed.entries[:20]:  # 最近20篇
        paper = {
            'title': entry.get('title', ''),
            'link': entry.get('link', ''),
            'summary': entry.get('summary', ''),
            'published': entry.get('published', ''),
            'authors': entry.get('author', 'Unknown')
        }
        papers.append(paper)
    
    return papers

def filter_papers(papers):
    """使用AI筛选相关文献"""
    filtered = []
    
    for paper in papers:
        prompt = f"""
        判断这篇论文是否与以下研究主题相关：{', '.join(TOPICS)}
        
        标题：{paper['title']}
        摘要：{paper['summary'][:500]}
        
        如果相关，回复：RELEVANT|相关主题|简要理由（50字内）
        如果不相关，回复：NOT_RELEVANT
        """
        
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100
            )
            
            result = response.choices[0].message.content.strip()
            
            if result.startswith('RELEVANT'):
                parts = result.split('|')
                paper['topic'] = parts[1] if len(parts) > 1 else 'General'
                paper['reason'] = parts[2] if len(parts) > 2 else ''
                paper['relevance_score'] = 85
                filtered.append(paper)
                
        except Exception as e:
            print(f"Error filtering paper: {e}")
            continue
    
    return sorted(filtered, key=lambda x: x['relevance_score'], reverse=True)

def generate_html(papers):
    """生成静态网页"""
    html_content = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>每日文献推送 - {datetime.now().strftime('%Y-%m-%d')}</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                max-width: 800px;
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
            .date {{
                text-align: center;
                color: #666;
                margin-bottom: 30px;
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
                font-size: 1.2em;
                font-weight: bold;
                color: #2d3748;
                margin-bottom: 8px;
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
                font-size: 0.9em;
                margin-bottom: 10px;
            }}
            .paper-topic {{
                display: inline-block;
                background: #667eea;
                color: white;
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 0.85em;
                margin-bottom: 10px;
            }}
            .paper-reason {{
                color: #4a5568;
                font-style: italic;
                font-size: 0.95em;
            }}
            .empty {{
                text-align: center;
                color: #718096;
                padding: 40px;
            }}
            .badge {{
                display: inline-block;
                background: #48bb78;
                color: white;
                padding: 2px 8px;
                border-radius: 12px;
                font-size: 0.75em;
                margin-left: 10px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📚 每日文献精选</h1>
            <div class="date">{datetime.now().strftime('%Y年%m月%d日')}</div>
            <div class="topics">
                <strong>关注领域：</strong>{', '.join(TOPICS)}
            </div>
    """
    
    if not papers:
        html_content += '<div class="empty">今日暂无相关文献更新</div>'
    else:
        for paper in papers:
            html_content += f"""
            <div class="paper">
                <div class="paper-title">
                    <a href="{paper['link']}" target="_blank">{paper['title']}</a>
                    <span class="badge">相关度 {paper['relevance_score']}%</span>
                </div>
                <div class="paper-meta">
                    👤 {paper['authors']} | 📅 {paper['published'][:10]}
                </div>
                <div class="paper-topic">🏷️ {paper['topic']}</div>
                <div class="paper-reason">💡 {paper['reason']}</div>
            </div>
            """
    
    html_content += """
        </div>
    </body>
    </html>
    """
    
    # 保存文件
    os.makedirs('docs', exist_ok=True)
    with open('docs/index.html', 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    # 同时保存JSON供历史记录
    with open('docs/papers.json', 'w', encoding='utf-8') as f:
        json.dump({
            'date': datetime.now().isoformat(),
            'topics': TOPICS,
            'papers': papers
        }, f, ensure_ascii=False, indent=2)

if __name__ == '__main__':
    print("正在获取文献...")
    papers = fetch_papers()
    print(f"获取到 {len(papers)} 篇文献")
    
    print("正在筛选相关文献...")
    filtered = filter_papers(papers)
    print(f"筛选出 {len(filtered)} 篇相关文献")
    
    print("生成网页...")
    generate_html(filtered)
    print("完成！")

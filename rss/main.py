from .rss_fetcher import fetch_all
from .redirect_resolver import resolve_and_extract

if __name__ == "__main__":
    queries = [
        "الاقتصاد المصري",
        "البورصة المصرية",
        "الجنيه المصري",
    ]
    
    # 24 Hours extraction milestone mapping
    print("⏳ Starting RSS Feed Discovery Pass...")
    df = fetch_all(queries, since_hours=24)
    
    print(f"\n🚀 Discovered {len(df)} initial records. Executing deep extraction loop...")
    
    if not df.empty:
        # Keep concurrency balanced for smooth processing inside GitHub action bounds
        df = resolve_and_extract(df, max_concurrent=5)
        
        output_filename = "rss_output.csv"
        df.to_csv(output_filename, index=False, encoding="utf-8-sig")
        print(f"\n✅ Execution loop complete. Extracted items saved to: '{output_filename}'")
    else:
        print("\n⚠️ Zero matching query elements found within the historical window parameter context.")
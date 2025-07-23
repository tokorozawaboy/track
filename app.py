import os
import json
import urllib.parse

from flask import Flask, render_template, request, redirect, url_for, session, jsonify

import pandas as pd
import numpy as np

from keiba_scraper import (
    get_schedule_races,
    get_daily_race_urls,
    get_race_name,
    scrape_yahoo_keiba_odds,
)

app = Flask(__name__)
app.secret_key = 'your-secret-key-please-change-this-in-production' 

SCORED_DATA_FILE_NAME = 'scored_historical_race_data.csv'
df_scored_global = None

def load_global_scored_data():
    global df_scored_global
    data_path = os.path.join(os.path.dirname(__file__), 'data', SCORED_DATA_FILE_NAME)
    if df_scored_global is None:
        try:
            df_scored_global = pd.read_csv(data_path, encoding='utf-8-sig')
            if '日付' in df_scored_global.columns:
                df_scored_global['日付_dt'] = pd.to_datetime(df_scored_global['日付'], format='%Y.%m.%d', errors='coerce')
            else:
                df_scored_global['日付_dt'] = pd.NaT
                print(f"WARNING: load_global_scored_data - '日付' column not found, '日付_dt' will be NaT.")
        except FileNotFoundError:
            print(f"ERROR: load_global_scored_data - Scored data file not found at {data_path}. Initializing empty DataFrame.")
            df_scored_global = pd.DataFrame()
        except Exception as e:
            print(f"ERROR: load_global_scored_data - An unexpected error occurred during data loading: {e}")
            df_scored_global = pd.DataFrame()

load_global_scored_data()


@app.route('/', methods=['GET', 'POST'])
def index():
    # セッションから復元データがあれば取得
    year = session.get('year')
    month = session.get('month')
    race_url_to_load = session.get('current_race_url')
    initial_horse_list = session.get('horse_list', [])
    initial_schedule_data = session.get('schedule_data', [])
    initial_daily_races_data = session.get('daily_races_data', [])

    # セッション復元フラグ
    is_restoring_session = False 

    if request.method == 'POST':
        is_restoring_session = True # POSTリクエストはセッション復元と判断

        # フォームデータからセッションを更新 (horse_career.htmlのgoBackToIndex()から送信されるデータ)
        session['year'] = int(request.form.get('year')) if request.form.get('year') else None
        session['month'] = int(request.form.get('month')) if request.form.get('month') else None
        
        race_url_form = request.form.get('race_url')
        session['current_race_url'] = urllib.parse.unquote(race_url_form) if race_url_form else None

        # JSONデータをデコードしてセッションに保存
        for key in ['horse_list', 'schedule_data', 'daily_races_data']:
            json_form_data = request.form.get(key)
            if json_form_data:
                try:
                    decoded_json_str = urllib.parse.unquote(json_form_data)
                    parsed_data = json.loads(decoded_json_str)
                    session[key] = parsed_data
                except json.JSONDecodeError as e:
                    print(f"ERROR: index - {key} JSONDecodeError for data starting '{json_form_data[:50]}...': {e}")
                    session[key] = []
                except Exception as e:
                    print(f"ERROR: index - Unexpected error processing {key}: {e}")
                    session[key] = []
            else:
                session[key] = []
            
    # GETリクエストの場合は、そのままセッションから読み込んだ値が使われる
    # POSTで戻ってきた場合は、更新されたセッションの値が使われる
    # initial_xxx 変数は、テンプレートへの引き渡し用にセッションの最新状態を反映

    return render_template(
        "index.html",
        year=year,
        month=month,
        race_url_to_load=race_url_to_load,
        initial_horse_list=initial_horse_list,
        initial_schedule_data=initial_schedule_data,
        initial_daily_races_data=initial_daily_races_data,
        is_restoring_session=is_restoring_session
    )


@app.route('/get_schedule', methods=['GET'])
def get_schedule_api():
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    if not year or not month:
        print(f"ERROR: get_schedule_api - Missing year or month.")
        return jsonify({"error": "年と月を正しく指定してください。"}), 400
    races = get_schedule_races(year, month)
    session['schedule_data'] = races # セッションに保存
    return jsonify(races)

@app.route('/get_daily_races', methods=['GET'])
def get_daily_races_api():
    url = request.args.get('url')
    if not url:
        print(f"ERROR: get_daily_races_api - URL parameter is missing.")
        return jsonify({"error": "URLパラメータがありません。"}), 400
    
    daily_race_urls_only = get_daily_race_urls(url)
    
    # 各URLからレース名を取得して完全なデータを作成
    processed_daily_races = []
    for race_item_url_only in daily_race_urls_only:
        race_name = get_race_name(race_item_url_only['URL']) 
        processed_daily_races.append({
            'レース番号': race_item_url_only['レース番号'],
            'URL': race_item_url_only['URL'],
            'レース名': race_name # レース名を追加
        })

    session['daily_races_data'] = processed_daily_races # セッションに保存
    return jsonify(processed_daily_races)

@app.route('/get_race_name', methods=['GET'])
def get_race_name_endpoint():
    url = request.args.get('url')
    if not url:
        return jsonify({"error": "URLパラメータがありません。"}), 400
    race_name = get_race_name(url)
    return jsonify({"race_name": race_name})


@app.route('/get_race_odds', methods=['GET'])
def get_race_odds_api():
    race_index_url = request.args.get('url')
    if not race_index_url:
        return jsonify({"error": "レースURLを正しく指定してください。"}), 400

    def generate_odds_url(index_url):
        parts = index_url.split('/')
        if not parts:
            return "無効なURL形式です。"
        race_id = parts[-1]
        return f"https://sports.yahoo.co.jp/keiba/race/odds/tfw/{race_id}"

    odds_url = generate_odds_url(race_index_url)
    scraped_odds_data = scrape_yahoo_keiba_odds(odds_url)

    if not scraped_odds_data:
        print(f"WARNING: オッズ情報を取得できませんでした for {odds_url}")
        return jsonify({"success": False, "error": "オッズ情報を取得できませんでした。"}), 500

    predictions = []
    if df_scored_global is None or df_scored_global.empty:
        print("WARNING: get_race_odds_api - Scored data is not loaded. Career scores will be N/A.")
        for horse in scraped_odds_data:
            predictions.append({
                '馬番': horse.get('馬番', 'N/A'),
                '馬名': horse.get('馬名', '---'),
                '単勝オッズ': horse.get('単勝オッズ', 'N/A'),
                '複勝オッズ': horse.get('複勝オッズ', 'N/A'),
                'キャリア最高スコア': 'N/A',
                'キャリア最高スコア日時': 'N/A'
            })
    else:
        for horse in scraped_odds_data:
            horse_name = horse.get('馬名', '---')
            max_score = 'N/A'
            max_date = 'N/A'
            horse_history = df_scored_global[df_scored_global['馬名'] == horse_name]
            if not horse_history.empty and '総合スコア_最終' in horse_history.columns:
                if horse_history['総合スコア_最終'].notna().any():
                    row = horse_history.loc[horse_history['総合スコア_最終'].idxmax()]
                    max_score = f"{row['総合スコア_最終']:.1f}"
                    max_date = row['日付']
            predictions.append({
                '馬番': horse.get('馬番', 'N/A'),
                '馬名': horse_name,
                '単勝オッズ': horse.get('単勝オッズ', 'N/A'),
                '複勝オッズ': horse.get('複勝オッズ', 'N/A'),
                'キャリア最高スコア': max_score,
                'キャリア最高スコア日時': max_date
            })

    session['current_race_url'] = race_index_url
    session['horse_list'] = predictions

    return jsonify({"success": True, "predictions": predictions})

# グラフデータ提供用の新しいAPIエンドポイント
@app.route('/horse_career_data/<horse_name>')
def horse_career_data(horse_name):
    decoded_horse_name = urllib.parse.unquote(horse_name)

    if df_scored_global is None or df_scored_global.empty:
        return jsonify({"error": "Historical data not loaded or empty"}), 500

    horse_data = df_scored_global[(df_scored_global['馬名'] == decoded_horse_name)].sort_values(by='日付_dt')

    if horse_data.empty:
        return jsonify({"labels": [], "datasets": [], "race_details": []})

    labels = horse_data['日付'].tolist()
    
    # グラフ描画用のスコアデータセット
    datasets = [
        {'label': '総合スコア', 'data': horse_data['総合スコア_最終'].tolist(), 'borderColor': 'rgba(255, 99, 132, 1)', 'backgroundColor': 'rgba(255, 99, 132, 0.2)'},
        {'label': '基礎能力スコア', 'data': horse_data['基礎能力スコア'].tolist(), 'borderColor': 'rgba(54, 162, 235, 1)', 'backgroundColor': 'rgba(54, 162, 235, 0.2)'},
        {'label': 'パフォーマンススコア', 'data': horse_data['パフォーマンススコア'].tolist(), 'borderColor': 'rgba(255, 206, 86, 1)', 'backgroundColor': 'rgba(255, 206, 86, 0.2)'},
        {'label': 'レースレベルスコア', 'data': horse_data['レースレベルスコア'].tolist(), 'borderColor': 'rgba(75, 192, 192, 1)', 'backgroundColor': 'rgba(75, 192, 192, 0.2)'}
    ]

    # ツールチップに表示するレース詳細情報も抽出
    race_details_for_tooltip = []
    for _, row in horse_data.iterrows():
        detail_dict = {}
        
        # クラス情報の取得ロジック（データに'クラス'カラムがあればそれを優先）
        race_class = 'N/A'
        # CSVファイルに存在する可能性のあるクラス関連のカラムを優先的にチェック
        if 'クラス' in row.index and pd.notna(row['クラス']):
            race_class = row['クラス']
        elif 'グレード' in row.index and pd.notna(row['グレード']): # 例: グレードカラムがある場合
            race_class = row['グレード']
        elif 'レース区分' in row.index and pd.notna(row['レース区分']): # 例: レース区分カラムがある場合
            race_class = row['レース区分']
        # それでも見つからなければ年齢限定や重量種別を代替として利用
        elif '年齢限定' in row.index and pd.notna(row['年齢限定']):
            race_class = row['年齢限定']
            if '性別限定' in row.index and pd.notna(row['性別限定']) and row['性別限定'] != 'なし':
                race_class += f"({row['性別限定']})"
        elif '重量種別' in row.index and pd.notna(row['重量種別']) and row['重量種別'] != '定量':
             race_class = row['重量種別']
        
        detail_dict['レース名'] = row['レース名'] if 'レース名' in row.index and pd.notna(row['レース名']) else 'N/A'
        detail_dict['クラス'] = race_class
        detail_dict['芝・ダ'] = row['芝・ダ'] if '芝・ダ' in row.index and pd.notna(row['芝・ダ']) else 'N/A'
        detail_dict['距離'] = row['距離'] if '距離' in row.index and pd.notna(row['距離']) else 'N/A'
        detail_dict['馬場状態'] = row['馬場状態'] if '馬場状態' in row.index and pd.notna(row['馬場状態']) else 'N/A'
        
        race_details_for_tooltip.append(detail_dict)


    # レスポンスにrace_details_for_tooltipを追加
    return jsonify({"labels": labels, "datasets": datasets, "race_details": race_details_for_tooltip})


@app.route('/horse_career/<horse_name>' , methods=['GET', 'POST'])
def horse_career_page(horse_name):
    decoded_horse_name = urllib.parse.unquote(horse_name)
    
    if request.method == 'POST':
        # このPOSTリクエストは「馬名オッズ一覧に戻る」ボタンからのみ発生すると想定
        # 受け取ったフォームデータをそのままindexルートに引き渡し、indexルートでセッションを更新させる
        return redirect(url_for('index', **request.form)) 
        
    # GETリクエストの場合 (馬名クリックによる直接遷移、またはリダイレクト後の表示)
    race_url_for_back = request.args.get('race_url')
    year_for_back = request.args.get('year')
    month_for_back = request.args.get('month')

    current_race_horse_list = session.get('horse_list', [])

    # df_scored_globalがない場合の処理
    if df_scored_global is None or df_scored_global.empty:
        return "戦歴データがロードされていないか、エラーが発生しました。", 500 # 元のコードの挙動を維持

    horse_data = df_scored_global[df_scored_global['馬名'] == decoded_horse_name].copy()
    if horse_data.empty:
        return f"馬名 '{decoded_horse_name}' の戦歴データがありませんでした。", 404

    if '日付_dt' not in horse_data.columns or horse_data['日付_dt'].isnull().all():
        return f"エラー: {decoded_horse_name} の日付データが不正です。", 500
    
    # Matplotlibでのグラフ画像生成部分は削除
    # horse_data_for_graph = horse_data.sort_values(by='日付_dt')
    # fig, ax = plt.subplots(figsize=(15, 6))
    # ... (plt.savefig() までのMatplotlibコードを全て削除) ...
    # image_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    # plt.close(fig)

    horse_data_for_table = horse_data.sort_values(by='日付_dt', ascending=False)
    score_cols = ['総合スコア_最終', '基礎能力スコア', 'レースレベルスコア', 'パフォーマンススコア',
                  '展開逆行B', 'マクリB', 'ハンデB', '上がり順位B', '上がりタイムB', '補正タイム']
    for col in score_cols:
        if col in horse_data_for_table.columns:
            horse_data_for_table[col] = horse_data_for_table[col].apply(lambda x: f"{x:.1f}" if pd.notna(x) else 'N/A')

    int_cols = ['着順', 'R', '年齢', '斤量', '1角', '2角', '3角', '4角', '上り3F順']
    for col in int_cols:
        if col in horse_data_for_table.columns:
            horse_data_for_table[col] = horse_data_for_table[col].apply(lambda x: str(int(x)) if pd.notna(x) else 'N/A')

    if '上り3F' in horse_data_for_table.columns:
        horse_data_for_table['上り3F'] = horse_data_for_table['上り3F'].apply(lambda x: f"{x:.2f}" if pd.notna(x) else 'N/A')

    display_columns = [
        '日付', '場所', 'レース名','芝・ダ','馬場状態', '距離','着順','決め手', 
        '総合スコア_最終', '基礎能力スコア', 'レースレベルスコア', 'パフォーマンススコア',
        '展開逆行B', 'マクリB', 'ハンデB', '上がり順位B', '上がりタイムB',
        '天気', '年齢限定', '性別限定', '重量種別',
        '性別', '年齢', '騎手', '斤量',
        '1角', '2角', '3角', '4角', '上り3F', '上り3F順'
    ]
    available_columns = [col for col in display_columns if col in horse_data_for_table.columns]
    horse_details = horse_data_for_table[available_columns].to_dict(orient='records')

    next_horse_name_loop = None
    prev_horse_name_loop = None
    if current_race_horse_list:
        horse_names_in_list = [h.get('馬名') for h in current_race_horse_list if h.get('馬名')]
        
        try:
            idx = horse_names_in_list.index(decoded_horse_name)
            num = len(horse_names_in_list)
            
            if num > 1:
                next_horse_name_loop = horse_names_in_list[(idx + 1) % num]
                prev_horse_name_loop = horse_names_in_list[(idx - 1 + num) % num]
            
        except ValueError:
            print(f"WARNING: '{decoded_horse_name}' は現在のレースの馬名リストに見つかりませんでした。")
            next_horse_name_loop = None
            prev_horse_name_loop = None

    return render_template(
        'horse_career.html',
        horse_name=decoded_horse_name,
        horse_details=horse_details,
        # image_base64はMatplotlibグラフを使わないため、渡さない (この変数はテンプレート側で参照されません)
        next_horse_name=next_horse_name_loop,
        prev_horse_name=prev_horse_name_loop,
        race_url_for_back=race_url_for_back,
        year_for_back=year_for_back,
        month_for_back=month_for_back
    )
    
if __name__ == '__main__':
    app.run(debug=True)
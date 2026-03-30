import streamlit as st
import anthropic
import base64
import json
import re
import csv
import io

st.set_page_config(page_title="ふるさと納税 CSV変換ツール", page_icon="📄")

st.title("📄 ふるさと納税 CSV変換ツール")
st.caption("寄付証明書PDF → TPS2000インポート用CSV（Shift-JIS）")

# セッション状態の初期化
if "all_results" not in st.session_state:
    st.session_state.all_results = []
if "csv_ready" not in st.session_state:
    st.session_state.csv_ready = False
if "csv_bytes" not in st.session_state:
    st.session_state.csv_bytes = None
if "csv_filename" not in st.session_state:
    st.session_state.csv_filename = ""

# APIキー入力
st.markdown("---")
api_key = st.text_input("APIキー（sk-ant-...）", type="password", placeholder="sk-ant-...")

if api_key and not api_key.startswith("sk-ant-"):
    st.error("APIキーが正しくありません。sk-ant- で始まるキーを入力してください。")
    api_key = None

# PDFアップロード
st.markdown("---")
uploaded_files = st.file_uploader(
    "寄付証明書PDFをアップロード",
    type="pdf",
    accept_multiple_files=True,
    help="複数ファイルまとめて選択できます"
)

if uploaded_files and api_key:
    if st.button("▶ AIで読み取り開始", type="primary"):
        st.session_state.all_results = []
        st.session_state.csv_ready = False
        st.session_state.csv_bytes = None

        client = anthropic.Anthropic(api_key=api_key)
        all_results = []
        errors = []

        prompt = """これはふるさと納税の寄付金受領証明書です。
以下のルールに従って情報を抽出し、JSONのみで返してください。説明文・前置き不要。

【抽出ルール】
1. donor_name（寄付者氏名）
   - 「氏名」「様」の近くに書かれた人名
   - 姓と名の間のスペースは除去する（例：「小笠原 秀樹」→「小笠原秀樹」）

2. donation_date（受領年月日）
   - 「受領年月日」「受領日」「寄附日」と書かれた日付を使う
   - 令和7年=2025年、令和6年=2024年として西暦に変換
   - YYYY/MM/DD形式で返す（例：2025/09/30）

3. municipality（自治体名）
   - 証明書を発行した自治体の都道府県名＋市区町村名のみ
   - 発行者欄（市長・町長の署名がある場所）から読み取る
   - 例：「三重県伊勢市」「北海道留萌市」「和歌山県有田川町」
   - 住所（寄付者の住所）と混同しないこと

4. amount（寄付金額）
   - 「寄附金額」「金」の後に続く数字
   - カンマや「円」「也」を除いた整数のみ
   - 例：「70,000円」→70000、「¥134,000」→134000

【重要】
- 1枚のPDFに複数の証明書が含まれる場合は全件抽出して配列で返す
- 読み取れない項目は空文字または0にする

返却形式（JSONのみ）:
[{"donor_name":"","donation_date":"","municipality":"","amount":0}]"""

        progress = st.progress(0)
        status = st.empty()

        for i, f in enumerate(uploaded_files):
            status.text(f"処理中: {f.name} ({i+1}/{len(uploaded_files)})")
            progress.progress(i / len(uploaded_files))

            try:
                b64 = base64.standard_b64encode(f.read()).decode("utf-8")
                response = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=2000,
                    messages=[{
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": "application/pdf",
                                    "data": b64
                                }
                            },
                            {"type": "text", "text": prompt}
                        ]
                    }]
                )
                text = response.content[0].text.strip()
                text = re.sub(r"```json|```", "", text).strip()
                parsed = json.loads(text)
                if not isinstance(parsed, list):
                    parsed = [parsed]
                all_results.extend(parsed)

            except Exception as e:
                errors.append(f"{f.name}: {e}")

        progress.progress(1.0)
        status.text("読み取り完了！")

        if errors:
            for err in errors:
                st.error(f"✗ {err}")

        if all_results:
            donor_name = all_results[0].get("donor_name", "氏名不明").replace(" ", "")
            year = all_results[0].get("donation_date", "")[:4] or "2025"
            csv_filename = f"{donor_name}_{year}_ふるさと納税.csv"

            header = ["寄附年月日", "(40文字)寄附先の所在地･名称", "金額"]
            rows = [
                [r.get("donation_date", ""), r.get("municipality", ""), r.get("amount", "")]
                for r in all_results
            ]

            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(header)
            writer.writerows(rows)
            csv_bytes = buf.getvalue().encode("shift_jis", errors="replace")

            st.session_state.all_results = all_results
            st.session_state.csv_bytes = csv_bytes
            st.session_state.csv_filename = csv_filename
            st.session_state.csv_ready = True

# 結果とダウンロードボタンの表示（セッション状態から）
if st.session_state.csv_ready and st.session_state.all_results:
    all_results = st.session_state.all_results
    st.success(f"✓ {len(all_results)}件 抽出完了　合計 {sum(int(r.get('amount', 0)) for r in all_results):,}円")

    st.markdown("### 抽出結果")
    table_data = [
        {
            "受領年月日": r.get("donation_date", ""),
            "自治体名": r.get("municipality", ""),
            "金額": f"{int(r.get('amount', 0)):,}円"
        }
        for r in all_results
    ]
    st.table(table_data)

    st.download_button(
        label="⬇ CSVをダウンロード",
        data=st.session_state.csv_bytes,
        file_name=st.session_state.csv_filename,
        mime="text/csv",
        key="csv_download"
    )

elif uploaded_files and not api_key:
    st.warning("APIキーを入力してください。")
elif api_key and not uploaded_files:
    st.info("PDFファイルをアップロードしてください。")

lIGA学習に使うlIGA1~4クラス色分け教師データ作成用のお絵描きアプリ<br>

ーーーーフォルダ構成ーーーー<br>
desktop/liga_annotation_project/app/
                            │    ├──liga_annotation_app.py<br>
　　　　　　　　　　　　　　　　　 　│ 　　├──liga_browser_app.py<br>
                            │    ├──liga_launcher_app.py<br>
                            │    ├──liga_review_approve_app.py<br>
                            │    └──requirements.txt<br>
                            │      <br>
                            └── data/
                                  ├──images/
                                  │     ├──01_pending<br>
                                  │     ├──02_skipped<br>
                                  │     ├──03_done<br>
                                  │     └──04_approved<br>
                                  ├──masks/
                                  │     ├──01_pending<br>
                                  │     ├──02_skipped<br>
                                  │     ├──03_done<br>
                                  │     └──04_approved<br>
                                  ├──meta/
                                  │     ├──01_pending<br>
                                  │     ├──02_skipped<br>
                                  │     ├──03_done<br>
                                  │     └──04_approved<br>
                                  └──overlays/
                                        ├──01_pending<br>
                                        ├──02_skipped<br>
                                        ├──03_done<br>
                                        └──04_approved<br>
<br>
ーーーー使い方ーーーー<br>
1.上記フォルダを作り、Pythonファイルとrequirements.txtを置く。<br>
2.仮想環境を作り、requirements.txtをインストールする。<br>
3.data/images/01_pendingに使用画像を入れる。<br>
4.liga_launcher_app.pyを実行。GUIが表示される。<br>
5.GUIのモード選択<br>
「作成モード（未編集画像）」：data/images/01_pendingの画像を順番に編集する。「スキップ（次へ）」を押すと画像はdata/images/02_skippedに移動される。<br>
「作成モード（保留画像）」：data/images/02_skippedの画像を編集する。<br>
「参照・修正・承認モード」：上記２つのモードで保存された画像（data/images/03_done）を参照と修正が可能。承認すると画像は04_approvedに移動される。<br>
「観覧モード」：画像を観覧するモード。選択した画像単発で「参照・修正・承認モード」への移行が可能。<br>

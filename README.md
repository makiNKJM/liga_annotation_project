lIGA学習に使うlIGA1~4クラス色分け教師データ作成用のお絵描きアプリ

ーーーーフォルダ構成ーーーー
desktop/liga_annotation_project/app/liga_annotation_app.py
　　　　　　　　　　　　　　　　　　　　　　　 /liga_browser_app.py
                                   /liga_launcher_app.py
                                   /liga_review_approve_app.py
                                   /requirements.txt
                                   
desktop/liga_annotation_project/data/images/01_pending
                                           /02_skipped
                                           /03_done
                                           /04_approved
                                    /masks/01_pending
                                          /02_skipped
                                          /03_done
                                          /04_approved
                                    /meta/01_pending
                                         /02_skipped
                                         /03_done
                                         /04_approved
                                    /overlays/01_pending
                                             /02_skipped
  　                                          /03_done
                                             /04_approved

ーーーー使い方ーーーー
1.上記フォルダを作り、Pythonファイルとrequirements.txtを置く。
2.仮想環境を作り、requirements.txtをインストールする。
3.data/images/01_pendingに使用画像を入れる。
4.liga_launcher_app.pyを実行。GUIが表示される。
5.GUIのモード選択
「作成モード（未編集画像）」：data/images/01_pendingの画像を順番に編集する。「スキップ（次へ）」を押すと画像はdata/images/02_skippedに移動される。
「作成モード（保留画像）」：data/images/02_skippedの画像を編集する。
「参照・修正・承認モード」：上記２つのモードで保存された画像（data/images/03_done）を参照と修正が可能。承認すると画像は04_approvedに移動される。
「観覧モード」：画像を観覧するモード。選択した画像単発で「参照・修正・承認モード」への移行が可能。

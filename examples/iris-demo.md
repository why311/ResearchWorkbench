# Iris分类实验：特征标准化是否改变分类结果？

这是一份本项目编写的流程示例研究说明，不是已发表论文，不用于证明方法新颖性。

## 方法
使用scikit-learn LogisticRegression进行三分类。原方案使用StandardScaler标准化特征；变体关闭标准化。两个方案使用同一个分层划分与随机种子。

## 数据与设定
数据集为scikit-learn内置Iris，共150个样本、4个特征、3个类别。测试集比例为0.3，采用分层划分，随机种子42。正则化参数C=1，最大迭代次数200。

## 评价指标
测试集Accuracy和Macro F1；保存逐样本预测与混淆矩阵。此说明未包含运行结果，指标必须由实际实验获得。

## 局限与未验证内容
小型数据集、单次数据划分；结果不代表其他任务，也不能支持统计显著性或普遍优越性结论。未来需在不同划分和其他数据集上检验。

## 原始来源
Iris数据：https://scikit-learn.org/stable/modules/generated/sklearn.datasets.load_iris.html
LogisticRegression：https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html
StandardScaler：https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.StandardScaler.html

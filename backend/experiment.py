"""A fixed, trusted experiment; external repository code never runs on the host."""
import argparse
import json
import platform
import importlib.metadata
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.datasets import load_iris
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, confusion_matrix, ConfusionMatrixDisplay
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    environment = {'python': platform.python_version(), 'packages': {
        name: importlib.metadata.version(name) for name in ['scikit-learn', 'numpy', 'matplotlib']}}
    (out / 'environment.json').write_text(json.dumps(environment, indent=2), encoding='utf-8')
    x, y = load_iris(return_X_y=True)
    print('Loaded sklearn Iris: 150 samples, 4 features, 3 classes', flush=True)
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=config['test_size'], random_state=config['seed'], stratify=y)
    model = LogisticRegression(C=config['regularization'], max_iter=config['max_iter'], random_state=config['seed'])
    if config['standardize']:
        model = make_pipeline(StandardScaler(), model)
    print(f'Train samples: {len(y_train)}; test samples: {len(y_test)}', flush=True)
    print(f'Parameters: {json.dumps(config)}', flush=True)
    model.fit(x_train, y_train)
    predicted = model.predict(x_test)
    metrics = {'accuracy': float(accuracy_score(y_test, predicted)),
               'macro_f1': float(f1_score(y_test, predicted, average='macro')),
               'train_samples': len(y_train), 'test_samples': len(y_test)}
    (out / 'metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    (out / 'predictions.csv').write_text('actual,predicted\n' + '\n'.join(f'{a},{b}' for a, b in zip(y_test, predicted)), encoding='utf-8')
    fig, ax = plt.subplots(figsize=(5, 4), dpi=160)
    ConfusionMatrixDisplay(confusion_matrix(y_test, predicted), display_labels=['setosa', 'versicolor', 'virginica']).plot(ax=ax, cmap='Blues', colorbar=False)
    fig.tight_layout()
    fig.savefig(out / 'confusion.png')
    plt.close(fig)
    print(f'Results: {json.dumps(metrics)}', flush=True)
    print('Saved metrics.json, predictions.csv, confusion.png', flush=True)


if __name__ == '__main__':
    main()

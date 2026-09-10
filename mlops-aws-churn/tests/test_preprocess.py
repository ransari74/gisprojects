import pandas as pd

from src.data.download_data import make_synthetic_data
from src.data.preprocess import build_feature_matrix, clean, engineer_features


def test_make_synthetic_data_shape_and_labels():
    df = make_synthetic_data(n_samples=200, seed=1)
    assert len(df) == 200
    assert set(df["Churn"].unique()) <= {"Yes", "No"}
    assert "TotalCharges" in df.columns


def test_clean_coerces_total_charges_and_binarizes_target():
    df = pd.DataFrame({
        "TotalCharges": ["100.5", " ", "50"],
        "Churn": ["Yes", "No", "Yes"],
    })
    cleaned = clean(df, target_column="Churn")
    assert cleaned["TotalCharges"].tolist() == [100.5, 0.0, 50.0]
    assert cleaned["Churn"].tolist() == [1, 0, 1]


def test_engineer_features_avoids_division_by_zero():
    df = pd.DataFrame({"tenure": [0, 5], "TotalCharges": [10.0, 50.0]})
    out = engineer_features(df)
    assert out["avg_monthly_spend"].tolist() == [10.0, 10.0]
    assert out["is_new_customer"].tolist() == [1, 0]


def test_build_feature_matrix_fit_and_transform_consistency():
    df = make_synthetic_data(n_samples=100, seed=2)
    df = clean(df, target_column="Churn")
    df = engineer_features(df)

    X_fit, encoder, scaler = build_feature_matrix(df, fit=True)
    X_transform, _, _ = build_feature_matrix(df, fit=False, encoder=encoder, scaler=scaler)

    assert X_fit.shape == X_transform.shape
    assert (X_fit == X_transform).all()

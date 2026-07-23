from sentence_transformers import CrossEncoder

model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
print(
    "Currency score:",
    model.predict(
        [
            (
                "currency formatting",
                "Never use the $ symbol; always write USD after the amount.",
            )
        ]
    ),
)
print(
    "K8s score:",
    model.predict(
        [
            (
                "Kubernetes on AWS",
                "Never use the $ symbol; always write USD after the amount.",
            )
        ]
    ),
)

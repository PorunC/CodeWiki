from backend.app.database import GraphCommunityRecord


def batches(items: list[GraphCommunityRecord], size: int):
    for index in range(0, len(items), size):
        yield items[index : index + size]

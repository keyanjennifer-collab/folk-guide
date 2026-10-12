"""正式商城商品目录（数据库驱动）。

商品名称、价格、图片与详情文案全部存入 ``products`` 表，由管理后台维护，
修改内容无需重新提审小程序。所有订单金额都在服务端根据数据库中的分价重新计算，
客户端上传的名称和金额一律不采信。

为了兼容已有下单与库存逻辑，本模块提供与旧硬编码目录同名的访问函数；
区别在于这些函数现在从数据库读取，且需要传入 ``db`` 会话。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from .commerce_models import Product


@dataclass(frozen=True)
class CatalogProduct:
    """一次读取中的商品快照；字段与订单计价所需一一对应。"""

    id: str
    name: str
    price_fen: int
    cost_fen: int
    category: str
    length_cm: float
    weight_grams: int
    active: bool = True

    # 图片与详情文案（供 /api/catalog 与小程序动态渲染）。
    color: str = ""
    element: str = ""
    beast: str = ""
    mood: str = ""
    scent: str = ""
    story: str = ""
    meaning: str = ""
    image: str = ""
    emblem: str = ""
    gallery: tuple[str, ...] = ()
    swatches: tuple[str, ...] = ()
    detail: dict = field(default_factory=dict)


def _from_row(row: Product) -> CatalogProduct:
    return CatalogProduct(
        id=row.id,
        name=row.name,
        price_fen=row.price_fen,
        cost_fen=row.cost_fen,
        category=row.category,
        length_cm=row.length_cm,
        weight_grams=row.weight_grams,
        active=row.active,
        color=row.color,
        element=row.element,
        beast=row.beast,
        mood=row.mood,
        scent=row.scent,
        story=row.story,
        meaning=row.meaning,
        image=row.image,
        emblem=row.emblem,
        gallery=_parse_json_list(row.gallery_json),
        swatches=_parse_json_list(row.swatches_json),
        detail=_parse_json_object(row.detail_json),
    )


def _parse_json_list(raw: str | None) -> tuple[str, ...]:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return ()
    return tuple(str(item) for item in value) if isinstance(value, list) else ()


def _parse_json_object(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def load_products(db: Session) -> list[CatalogProduct]:
    """按排序读取全部商品（含已下架），供后台和计价使用。"""
    rows = db.scalars(select(Product).order_by(Product.sort_order, Product.id)).all()
    return [_from_row(row) for row in rows]


def product_or_none(db: Session, product_id: str) -> CatalogProduct | None:
    """按 ID 读取单个商品；不存在时返回 None。"""
    row = db.get(Product, product_id)
    return _from_row(row) if row else None


def product_by_id(db: Session) -> dict[str, CatalogProduct]:
    """一次性读取全部商品，构建 id -> 商品 的映射。"""
    return {product.id: product for product in load_products(db)}


def seed_products(db: Session) -> int:
    """首次建库时写入首批 6 个商品；已存在的商品不会被覆盖。

    只在 ``products`` 表为空时执行，避免覆盖后台后续的编辑内容。
    """
    existing = db.scalar(select(Product.id).limit(1))
    if existing is not None:
        return 0
    seeds: Sequence[dict] = (
        {
            "id": "gift", "name": "五色知时线香套装", "price_fen": 26800, "category": "set",
            "length_cm": 10.5, "weight_grams": 75, "sort_order": 0, "active": True,
            "color": "五色", "element": "五行", "beast": "五方图腾", "mood": "五色齐备 · 随时择香",
            "scent": "五款线香与矿石香插，收于一盒。",
            "story": "将青木、朱蜜、黄檀、白桂、墨沉五款香气收于一盒。随时序择色，也随心择香。",
            "meaning": "五色齐备，寓意在不同日常里都能找到一份适合自己的安定与从容。",
            "image": "gift.jpg", "emblem": "logo.png",
            "gallery": ["gift.jpg", "gift-gallery.jpg", "gift-open.jpg", "five-set.jpg"],
            "swatches": ["#60734e", "#9c3b36", "#b8893c", "#e1d8c9", "#303735"],
        },
        {
            "id": "green", "name": "青木", "price_fen": 6800, "category": "single",
            "length_cm": 10.5, "weight_grams": 15, "sort_order": 1, "active": True,
            "color": "青色", "element": "木", "beast": "青龙", "mood": "草木清润",
            "scent": "沉香 · 檀香 · 灵香 · 排草",
            "story": "清凉木气转入柔润檀香，余韵微甜而清醒。留一缕草木气，陪伴阅读与日常。",
            "meaning": "青木寓意生长与更新，适合把心绪慢慢打开，重新开始。",
            "image": "green.jpg", "emblem": "green-emblem-v2.png",
            "gallery": ["green.jpg", "green-detail.jpg"],
            "swatches": ["#8c9e78", "#627354", "#344a37"],
        },
        {
            "id": "red", "name": "朱蜜", "price_fen": 6800, "category": "single",
            "length_cm": 10.5, "weight_grams": 15, "sort_order": 2, "active": True,
            "color": "赤色", "element": "火", "beast": "朱雀", "mood": "暖甜明烈",
            "scent": "檀香 · 沉香 · 降真香 · 琥珀",
            "story": "木香中透出柔软蜜意，尾韵温厚。让一缕暖香，为相聚的时刻添一点温度。",
            "meaning": "朱蜜寓意热烈与相聚，把温暖和表达留给重要的人与时刻。",
            "image": "red.jpg", "emblem": "red-emblem-v2.png",
            "gallery": ["red.jpg", "red-detail.jpg"],
            "swatches": ["#bb5c52", "#953b36", "#672927"],
        },
        {
            "id": "gold", "name": "黄檀", "price_fen": 6800, "category": "single",
            "length_cm": 10.5, "weight_grams": 15, "sort_order": 3, "active": True,
            "color": "黄色", "element": "土", "beast": "麒麟", "mood": "温润从容",
            "scent": "老檀香 · 温润木韵",
            "story": "柔和的檀木香慢慢铺开，清甜而温润。在熟悉的日常里，留一点从容。",
            "meaning": "黄檀寓意安定与丰足，在熟悉的日常里守住从容和踏实。",
            "image": "gold.jpg", "emblem": "gold-emblem-v2.png",
            "gallery": ["gold.jpg"],
            "swatches": ["#ddb266", "#b6812e", "#776141"],
        },
        {
            "id": "white", "name": "白桂", "price_fen": 6800, "category": "single",
            "length_cm": 10.5, "weight_grams": 15, "sort_order": 4, "active": True,
            "color": "白色", "element": "金", "beast": "白虎", "mood": "清简收敛",
            "scent": "沉香 · 檀香 · 乳香 · 桂花",
            "story": "干净木香与桂花的清甜相遇，乳香让尾韵更柔和。适合留给自己的一段安静时光。",
            "meaning": "白桂寓意清明与收敛，给自己留一段专注而安静的时间。",
            "image": "white.jpg", "emblem": "white-emblem-v2.png",
            "gallery": ["white.jpg", "white-detail.jpg"],
            "swatches": ["#f2eee5", "#dcd0bf", "#aaa69e"],
        },
        {
            "id": "black", "name": "墨沉", "price_fen": 6800, "category": "single",
            "length_cm": 10.5, "weight_grams": 15, "sort_order": 5, "active": True,
            "color": "黑色", "element": "水", "beast": "玄武", "mood": "幽沉安定",
            "scent": "沉香 · 檀香 · 降香",
            "story": "凉香绵长，木韵内敛，尾端留有温厚的木质甜意。适合独处、复盘与缓慢思考。",
            "meaning": "墨沉寓意沉静与守心，适合独处、复盘和慢慢思考。",
            "image": "black.jpg", "emblem": "black-emblem-v2.png",
            "gallery": ["black.jpg", "black-detail-1.jpg", "black-detail-2.jpg"],
            "swatches": ["#161b1a", "#343a38", "#616b67"],
        },
    )
    for item in seeds:
        db.add(Product(
            id=item["id"], name=item["name"], price_fen=item["price_fen"],
            category=item["category"], length_cm=item["length_cm"],
            weight_grams=item["weight_grams"], sort_order=item["sort_order"],
            active=item["active"], color=item["color"], element=item["element"],
            beast=item["beast"], mood=item["mood"], scent=item["scent"],
            story=item["story"], meaning=item["meaning"], image=item["image"],
            emblem=item["emblem"],
            gallery_json=json.dumps(item["gallery"], ensure_ascii=False),
            swatches_json=json.dumps(item["swatches"], ensure_ascii=False),
            detail_json="{}",
        ))
    db.commit()
    return len(seeds)

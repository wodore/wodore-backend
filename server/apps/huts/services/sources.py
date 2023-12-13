import os

# from fastapi import Depends
# from sqlalchemy import or_, select, and_, func
import sys
from typing import Tuple

# import asyncio
from deepdiff import DeepDiff

from django.core.exceptions import ObjectDoesNotExist

# from sqlmodel.ext.asyncio.session import AsyncSession
# from sqlalchemy.orm import selectinload
from server.apps.huts.models import HutSource, ReviewStatusChoices
from server.apps.huts.schemas.status import CreateOrUpdateStatus

if __name__ == "__main__":  # only for testing
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    sys.path.append(root_dir)
    from rich.traceback import install

    install(show_locals=False)

# from app.models.utils.hut_fields import ReviewStatusChoices
#
# from app.models.utils.hut_fields import ReviewStatusChoices

# from app.models.ref import RefDatabase, HutRefLink
# from app.models.hut import HutDatabase, Hut, Point
# from app.models.hut import Point
# from app.models.reference.hut_source import HutSource, HutSource
# from app.services.ref import RefService

# from app.hut.schemas.hut import LoginResponseSchema
# from core.db import Transactional, get_async_session, get_return_async_session, set_session_context, async_engine
# from huts.schemas.status import CreateOrUpdateStatus
# from app.models.reference import HutSourceTypes
#
# from time import perf_counter_ns
#
# from pydantic import BaseModel
#
# from geojson_pydantic import FeatureCollection
# from functools import lru_cache


class HutSourceService:
    # def __init__(self, session: AsyncSession = Depends(get_async_session)):
    #     self.session = session

    # async def get_source_by_id(self, id:int) -> Optional[HutSource]:
    #     query = select(HutSource).filter_by(id = id)
    #     result = await self.session.execute(query)
    #     return result.scalar()

    # async def get_current_source_list(self,
    #                           ref_slug : Optional[str] = None,
    #                           is_active: Optional[bool] = True,
    #                           review_status: Optional[ReviewStatusChoices] = None,
    #                           **kwargs
    #                           ) -> Optional[List[HutSource]]:
    #     kwargs["is_active"] = is_active
    #     kwargs["review_status"] = review_status
    #     huts = await self.get_source_list(ref_slug=ref_slug,
    #                                         is_current=True, **kwargs)
    #     return huts
    #
    # async def get_source_by(self,
    #                           source_id : str,
    #                           ref_slug : str,
    #                           is_active: Optional[bool] = None) -> Optional[HutSource]:
    #     _huts = await self.get_source_list(source_id=source_id, ref_slug=ref_slug, limit=1, is_active=is_active)
    #     if _huts:
    #         hut_src = _huts[0]
    #     else:
    #         hut_src = None
    #     return hut_src

    # async def get_source_list(self,
    #                           source_id : Optional[str] = None,
    #                           ref_slug : Optional[str] = None,
    #                           point: Optional[Point] = None,
    #                           radius_meter: int= 2,
    #                           limit: int = 1000,
    #                           review_status: Optional[ReviewStatusChoices] = None,
    #                           is_active: Optional[bool] = None,
    #                           is_current: Optional[bool] = None,
    #                           order_by = HutSource.created_at.desc()) -> Optional[List[HutSource]]:
    #     query = select(HutSource)
    #     if source_id is not None:
    #         query = query.filter_by(source_id = source_id)
    #     if point is not None:
    #         query = query.filter(point.get_within(from_column=HutSource.point, inside_radius_m=radius_meter))
    #     if ref_slug is not None:
    #         query = query.filter_by(ref_slug = ref_slug)
    #     if is_active is not None:
    #         query = query.filter_by(is_active = is_active)
    #     if is_current is not None:
    #         query = query.filter_by(is_current = is_current)
    #     if review_status is not None:
    #         query = query.filter_by(review_status = review_status)
    #
    #     query = query.limit(limit).order_by(order_by)
    #     result = await self.session.execute(query)
    #     return result.scalars().all()

    # # @Transactional() # --> does not work correct. session does nothing, wrong session?
    def create(
        self,
        hut_source: HutSource,
        new_review_status: ReviewStatusChoices = ReviewStatusChoices.new
        # commit: bool = True,
        # refresh: bool = True,
        # update_existing: bool = False, overwrite_existing_fields: bool = False,
        # ref_slug: Union[str, None] = None,
    ) -> Tuple[HutSource, CreateOrUpdateStatus]:
        # check if already in DB
        status: CreateOrUpdateStatus = CreateOrUpdateStatus.ignored
        # other_hut_src = await self.get_source_by(source_id=hut_source.source_id, ref_slug=hut_source.ref_slug)
        try:
            other_hut_src = HutSource.objects.get(
                source_id=hut_source.source_id, organization=hut_source.organization, is_current=True
            )
            # if other_hut_src:
            if other_hut_src.is_active is False:  # ignore if not active
                return hut_source, CreateOrUpdateStatus.ignored
            # diff = DeepDiff(other_hut_src.source_data.dict(), hut_source.source_data.dict())
            diff = DeepDiff(
                other_hut_src.source_data,
                hut_source.source_data,
                ignore_type_in_groups=[DeepDiff.numbers, (list, tuple)],
            )
            if diff:  # something changed, add a new entry:
                diff_comment = (
                    diff.pretty()
                    .replace("root[", "")
                    .replace("']['", ".")
                    .replace("']", "'")
                    .replace("'[", "[")
                    .replace("]['", "].")
                    .replace("] ", "]' ")
                )
                if other_hut_src.review_status == ReviewStatusChoices.review and other_hut_src.review_comment:
                    diff_comment += f"\n\nComments from version {other_hut_src.version}: {other_hut_src.review_comment}"
                if len(diff_comment) >= 3000:
                    diff_comment = "alot changed, have a look ..."
                hut_source.review_comment = diff_comment
                hut_source.review_status = ReviewStatusChoices.review
                if other_hut_src is not None:
                    hut_source.previous_object = other_hut_src
                hut_source.version = other_hut_src.version + 1
                hut_source.save()
                # self.session.add(hut_source)
                other_hut_src.review_status = ReviewStatusChoices.old
                other_hut_src.is_current = False
                other_hut_src.save()
                status = CreateOrUpdateStatus.updated
            else:
                hut_source = other_hut_src
                status = CreateOrUpdateStatus.exists
        except ObjectDoesNotExist:
            # else:  # new entry, does not exist yet
            # hut_source.review_comment = ""
            hut_source.review_status = new_review_status
            hut_source.save()
            # self.session.add(hut_source)
            status = CreateOrUpdateStatus.created
        # if commit:
        #    await self.session.commit()
        # if commit and refresh:
        #    await self.session.refresh(hut_source)
        return hut_source, status


# async def get_hut_source_service(session: AsyncSession = Depends(get_async_session)) -> HutSourceService:
#    return HutSourceService(session=session)
#
#
# async def main():
#    limit = 10
#    session_id = str(uuid4())
#    context = set_session_context(session_id=session_id)
#    session = await get_return_async_session()
#    async with session as s:
#        hut_src_service = HutSourceService(session=session)
#        huts = await hut_src_service.get_current_source_list(ref_slug="sac", limit=10)
#        for src_hut in huts:
#            hut = src_hut.source_data.get_hut()
#            hut.name = "Updated"
#            # rprint(hut.source_data.rich(hide_none=True))
#            # if hut.review_comment and hut.review_comment != "new entry":
#            #    rprint(Text.assemble(("REVIEW: ", "bold"),(f"{hut.review_comment}","magenta")))
#
#        ##rprint(huts)
#        ###rprint(f"Length: {len(huts)}")
#        # point = Point(lon=7.9735559, lat=46.4245463)
#        # huts = await hut_src_service.get_source_list(point=point, limit=4, ref_slug="osm")
#        # if len(huts):
#        #    for h in huts:
#        #        rprint(h)
#        # else:
#        #    rprint(f"Did not find anything")
#        # if len(huts) >= 1:
#        #    huts[0].source_data.tags.ele = 3433
#        #    huts[0].source_data_changed()
#        # if len(huts) >= 2:
#        #    huts[1].source_data.tags.ele = 1000
#        #    huts[1].source_data_changed()
#        #    diff = DeepDiff(dict(huts[1].source_data), dict(huts[0].source_data))
#        #    diff_comment = diff.pretty().replace("root[","").replace("']['",".").replace("']", "'")
#        #    rprint(diff_comment)
#        #    comment = f"{huts[0].review_comment}\n\n" if huts[0].review_comment is not None else ""
#        #    if diff_comment not in comment:
#        #        huts[0].review_comment = comment + diff_comment
#        # await s.commit()
#    await async_engine.dispose()  # TODO: why? shoudl use yield session generator
#    # rprint(h.rich(hide_none=True))
#    # huts = await osm_service.get_hut_list(limit)
#    # for h in huts:
#    #    click.echo(f"{h.name} ({h.slug})")
#
#
# if __name__ == "__main__":
#    asyncio.run(main())

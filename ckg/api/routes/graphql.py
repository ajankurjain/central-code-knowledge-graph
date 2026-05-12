"""Wire the Strawberry schema into FastAPI with the same API-token auth."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from strawberry.fastapi import GraphQLRouter

from ckg.api.graphql_schema import schema
from ckg.auth import Principal, require_repo_read

router = APIRouter(tags=["graphql"])


async def _context(principal: Principal = Depends(require_repo_read)) -> dict:
    return {"principal": principal}


# Recent strawberry-graphql versions renamed `graphiql=True` to
# `graphql_ide="graphiql"`. We pass the new name when supported and fall back
# to the no-arg form (default still serves GraphiQL) so the same code works
# against any reasonably current strawberry-graphql.
try:
    _graphql_app = GraphQLRouter(
        schema,
        context_getter=_context,
        graphql_ide="graphiql",
    )
except TypeError:
    _graphql_app = GraphQLRouter(schema, context_getter=_context)

# Mount the Strawberry router. `include_in_schema=False` keeps it out of the
# auto-generated OpenAPI (which only describes REST).
router.include_router(_graphql_app, prefix="/graphql", include_in_schema=False)

"""Route handlers for static docs."""



from fastapi import APIRouter

from starlette.responses import Response



from job_hunter_agent.paths import DATA_DIR, STATIC_DIR

from job_hunter_agent import server_helpers as srv



from job_hunter_agent.routes.responses import guess_media_type, json_response



router = APIRouter()





@router.get("/static/{resource_path:path}")

def static_file(resource_path: str):  # type: ignore[no-untyped-def]

    relative = resource_path.strip("/")

    candidate = (STATIC_DIR / relative).resolve()

    static_root = STATIC_DIR.resolve()

    if static_root not in candidate.parents and candidate != static_root:

        return json_response({"error": "Static asset not found"}, 404)

    if not candidate.is_file():

        return json_response({"error": "Static asset not found"}, 404)

    return Response(

        content=candidate.read_bytes(),

        media_type=guess_media_type(candidate),

        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},

    )





@router.get("/data/{resource_path:path}")

def data_file(resource_path: str):  # type: ignore[no-untyped-def]

    relative = resource_path.strip("/")

    candidate = (DATA_DIR / relative).resolve()

    data_root = DATA_DIR.resolve()

    if data_root not in candidate.parents and candidate != data_root:

        return json_response({"error": "Data asset not found"}, 404)

    if not candidate.is_file():

        return json_response({"error": "Data asset not found"}, 404)

    return Response(

        content=candidate.read_bytes(),

        media_type=guess_media_type(candidate),

        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},

    )





@router.get("/docs")

@router.get("/api/docs")

def api_docs():  # type: ignore[no-untyped-def]

    return json_response({"docs": srv.get_docs()})


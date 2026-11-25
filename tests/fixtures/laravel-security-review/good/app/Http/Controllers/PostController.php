<?php

namespace App\Http\Controllers;

use App\Http\Requests\StorePostRequest;
use App\Models\Post;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Gate;

class PostController extends Controller
{
    public function index(Request $request)
    {
        $sort = in_array($request->input('sort'), ['title', 'created_at'], true) ? $request->input('sort') : 'id';

        return view('posts.index', [
            'posts' => Post::where('title', 'like', '%'.$request->q.'%')->orderBy($sort)->paginate(),
        ]);
    }

    public function store(StorePostRequest $request)
    {
        return redirect()->route('posts.show', Post::create($request->validated()));
    }

    public function update(Request $request, Post $post)
    {
        Gate::authorize('update', $post);
        $post->update($request->only(['title', 'body']));

        return back();
    }

    public function destroy(Post $post)
    {
        $this->authorize('delete', $post);
        $post->delete();

        return back();
    }
}
